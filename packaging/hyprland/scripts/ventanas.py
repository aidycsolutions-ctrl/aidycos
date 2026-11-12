#!/usr/bin/env python3
"""Windows-style window management for floating Hyprland windows (Jugoo).

Every window floats; this script arranges them like a classic desktop:

  minimize [ADDR]        send to special:minimizados (remembers origin)
  restore [ADDR]         bring back the last (or given) minimized window
  restore-all            bring back every minimized window
  focus ADDR             taskbar click: restore / minimize / focus
  alt-tab [prev]         cycle windows on the current desktop (raise + focus)
  close [ADDR]           close the window
  max [ADDR]             toggle maximized (snap-to-work-area) / restore size
  up [ADDR]              maximize
  down [ADDR]            restore a snapped window, otherwise minimize
  left | right | top-left | top-right | bottom-left | bottom-right [ADDR]
  split2 | split4 | grid | cascade [ADDR]
                         arrange the workspace of ADDR (default: active one)
  daemon                 FIFO command server + snap on hyprbars drag end

The ``ventanas`` shell wrapper writes commands to the daemon FIFO so key binds
and title-bar buttons react without starting Python each time.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import stat
import sys
from typing import Any

from decoraciones import classes_in_rules, client_draws_title_buttons, updated_rules

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
CSD_RULES = Path.home() / ".config/hypr/config/jugoo_hyprbars_csd.conf"
FIFO = RUNTIME / "jugoo-ventanas.fifo"
PIDFILE = RUNTIME / "jugoo-ventanas.pid"
STATE_FILE = RUNTIME / "jugoo-ventanas.json"

MINIMIZED_WS = "special:minimizados"
GAP = 8
# Keep maximized/snapped windows clear of the Jugoo top bar even if the
# compositor reports a collapsed exclusive zone (bar-retract edge cases).
SHELL_TOP_MIN = 57
# Apps that should open snapped to the work area under the Jugoo bar.
_AUTO_MAX_CLASS = re.compile(
    r"^(firefox(?:-esr)?|org\.mozilla\.firefox)$",
    re.IGNORECASE,
)
# Cursor distance from a screen edge that snaps on release (Windows-style).
SNAP_MARGIN = 36
# Both edges count as a corner only this close to the actual corner.
CORNER_PX = 96
# How far a placed window may drift before we stop treating it as that snap.
NEAR_PX = 80
SIZE_TOLERANCE = 6
TITLE_BAR_FALLBACK = 28
CASCADE_STEP = 32
SHELL_CLASS = "com.jugoo.Shell"

Rect = tuple[int, int, int, int]


class HyprError(RuntimeError):
    pass


# --------------------------------------------------------------------- IPC


def _hypr_dir() -> Path:
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not signature:
        raise HyprError("HYPRLAND_INSTANCE_SIGNATURE no está definido")
    return RUNTIME / "hypr" / signature


def request(command: str) -> str:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(str(_hypr_dir() / ".socket.sock"))
            sock.sendall(command.encode())
            chunks: list[bytes] = []
            while chunk := sock.recv(65536):
                chunks.append(chunk)
    except OSError as error:
        raise HyprError(f"IPC de Hyprland falló: {error}") from error
    return b"".join(chunks).decode("utf-8", errors="replace")


def query(name: str) -> Any:
    try:
        return json.loads(request(f"j/{name}"))
    except json.JSONDecodeError as error:
        raise HyprError(f"respuesta inválida para {name}") from error


def dispatch(*commands: str) -> None:
    if commands:
        request("[[BATCH]]" + ";".join(f"dispatch {command}" for command in commands))


def notify(message: str) -> None:
    try:
        request(f"notify -1 3500 0 Ventanas: {message}")
    except HyprError:
        pass


# ------------------------------------------------------------------- state


def load_state() -> dict[str, Any]:
    try:
        state = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    snaps = state.get("snaps")
    minimized = state.get("minimized")
    return {
        "snaps": snaps if isinstance(snaps, dict) else {},
        "minimized": minimized if isinstance(minimized, list) else [],
    }


def save_state(state: dict[str, Any]) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE_FILE)


# ---------------------------------------------------------------- geometry


def normalize_address(address: str) -> str:
    address = address.strip().lower()
    return address if address.startswith("0x") else f"0x{address}"


def geometry(window: dict[str, Any]) -> Rect:
    x, y = window["at"]
    width, height = window["size"]
    return int(x), int(y), int(width), int(height)


def same_size(a: Rect | list[int], b: Rect | list[int]) -> bool:
    return abs(a[2] - b[2]) <= SIZE_TOLERANCE and abs(a[3] - b[3]) <= SIZE_TOLERANCE


def near_rect(a: Rect | list[int], b: Rect | list[int], slop: int = NEAR_PX) -> bool:
    """True when two boxes are the same window placement, allowing compositor drift."""
    return all(abs(int(a[i]) - int(b[i])) <= slop for i in range(4))


def monitor_bounds(monitor: dict[str, Any]) -> Rect:
    scale = float(monitor.get("scale") or 1.0)
    width = round(monitor["width"] / scale)
    height = round(monitor["height"] / scale)
    if int(monitor.get("transform") or 0) % 2:
        width, height = height, width
    return int(monitor["x"]), int(monitor["y"]), width, height


def work_area(monitor: dict[str, Any]) -> Rect:
    x, y, width, height = monitor_bounds(monitor)
    left, top, right, bottom = (list(monitor.get("reserved") or []) + [0, 0, 0, 0])[:4]
    top = max(int(top), SHELL_TOP_MIN)
    return x + left, y + top, width - left - right, height - top - bottom


def monitor_by_id(monitor_id: int) -> dict[str, Any]:
    monitors = query("monitors")
    for monitor in monitors:
        if monitor.get("id") == monitor_id:
            return monitor
    return next((m for m in monitors if m.get("focused")), monitors[0])


def monitor_at(x: int, y: int) -> dict[str, Any]:
    monitors = query("monitors")
    for monitor in monitors:
        mx, my, mw, mh = monitor_bounds(monitor)
        if mx <= x < mx + mw and my <= y < my + mh:
            return monitor
    return next((m for m in monitors if m.get("focused")), monitors[0])


_bar_height: int | None = None


def bar_height() -> int:
    """Height of the hyprbars title bar drawn above each client (0 if absent)."""
    global _bar_height
    if _bar_height is not None:
        return _bar_height
    try:
        enabled = json.loads(request("j/getoption plugin:hyprbars:enabled"))
        if not int(enabled.get("int", 1)):
            _bar_height = 0
            return 0
        raw = json.loads(request("j/getoption plugin:hyprbars:bar_height"))
        _bar_height = max(0, int(raw.get("int", TITLE_BAR_FALLBACK)))
    except (HyprError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        _bar_height = TITLE_BAR_FALLBACK
    return _bar_height


_own_titlebar_classes: set[str] = set()


def window_bar_height(window: dict[str, Any]) -> int:
    """0 when this window already draws its own caption buttons."""
    if str(window.get("class") or "") in _own_titlebar_classes:
        return 0
    return bar_height()


def _executable(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return ""


def _draws_title_buttons(window: dict[str, Any]) -> bool:
    """Re-check with current heuristics (do not trust stale CSD rule cache)."""
    class_name = str(window.get("class") or "")
    if not class_name or class_name == SHELL_CLASS:
        return False
    pid = int(window.get("pid") or 0)
    return client_draws_title_buttons(
        class_name=class_name,
        executable=_executable(pid),
    )


def sync_titlebars() -> None:
    """Hide hyprbars on clients that already have minimize, maximize and close."""
    global _own_titlebar_classes
    detected = {
        str(window.get("class") or "")
        for window in query("clients")
        if _draws_title_buttons(window)
    }
    detected.discard("")
    previous = CSD_RULES.read_text(encoding="utf-8") if CSD_RULES.is_file() else ""
    rendered = updated_rules(previous, detected)
    if rendered is None:
        _own_titlebar_classes = classes_in_rules(previous)
        return
    CSD_RULES.parent.mkdir(parents=True, exist_ok=True)
    temporary = CSD_RULES.with_suffix(CSD_RULES.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(CSD_RULES)
    _own_titlebar_classes = classes_in_rules(rendered)
    request("reload config-only")


def zone_rect(zone: str, area: Rect) -> Rect:
    x, y, width, height = area
    x, y, width, height = x + GAP, y + GAP, width - 2 * GAP, height - 2 * GAP
    half_w = (width - GAP) // 2
    half_h = (height - GAP) // 2
    right_x = x + half_w + GAP
    bottom_y = y + half_h + GAP
    return {
        "max": (x, y, width, height),
        "left": (x, y, half_w, height),
        "right": (right_x, y, width - half_w - GAP, height),
        "top-left": (x, y, half_w, half_h),
        "top-right": (right_x, y, width - half_w - GAP, half_h),
        "bottom-left": (x, bottom_y, half_w, height - half_h - GAP),
        "bottom-right": (right_x, bottom_y, width - half_w - GAP, height - half_h - GAP),
    }[zone]


def grid_rects(count: int, area: Rect, columns: int | None = None) -> list[Rect]:
    """Split the work area into ``count`` tiles; short last row stretches."""
    if count <= 0:
        return []
    x, y, width, height = area
    x, y, width, height = x + GAP, y + GAP, width - 2 * GAP, height - 2 * GAP
    columns = columns or math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)
    tile_h = (height - GAP * (rows - 1)) // rows
    rects: list[Rect] = []
    for row in range(rows):
        in_row = min(columns, count - row * columns)
        tile_w = (width - GAP * (in_row - 1)) // in_row
        for column in range(in_row):
            rects.append(
                (x + column * (tile_w + GAP), y + row * (tile_h + GAP), tile_w, tile_h)
            )
    return rects


def client_rect(rect: Rect, bar: int) -> Rect:
    """Hyprland positions the client surface; the title bar sits above it.

    ``rect`` is the outer frame, already inside the work area (below the shell
    bar). The client is shifted down so the title bar stays inside that frame.
    """
    x, y, width, height = rect
    return x, y + bar, width, max(height - bar, 80)


def default_float(area: Rect, bar: int) -> Rect:
    """Centered size used when un-maximizing a window we never saw smaller."""
    ax, ay, aw, ah = area
    outer_w = max(int(aw * 0.72), 480)
    outer_h = max(int(ah * 0.72), 320)
    x = ax + max(GAP, (aw - outer_w) // 2)
    y = ay + max(GAP, (ah - outer_h) // 2)
    return client_rect((x, y, outer_w, outer_h), bar)


def fills_work_area(geom: Rect | list[int], area: Rect, bar: int) -> bool:
    """True when the outer frame (client plus title bar) covers almost the work area."""
    _x, _y, width, height = (int(v) for v in geom)
    _ax, _ay, aw, ah = area
    if aw <= 0 or ah <= 0:
        return False
    return width >= aw * 0.88 and (height + max(bar, 0)) >= ah * 0.88


# ---------------------------------------------------------------- windows


def is_managed(window: dict[str, Any]) -> bool:
    return (
        bool(window.get("address"))
        and window.get("mapped", True)
        and not window.get("hidden", False)
        and window.get("class") != SHELL_CLASS
        and not str(window.get("title", "")).startswith("Jugoo ")
    )


def is_minimized(window: dict[str, Any]) -> bool:
    return (window.get("workspace") or {}).get("name") == MINIMIZED_WS


def _focus_history_id(window: dict[str, Any]) -> int:
    raw = window.get("focusHistoryID")
    if raw is None:
        return 10**9
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 10**9


def most_recent_managed(*, allow_minimized: bool = False) -> dict[str, Any] | None:
    """Window the user was last using (survives focus lost to the Jugoo layer bar)."""
    windows = [
        window
        for window in query("clients")
        if is_managed(window) and (allow_minimized or not is_minimized(window))
    ]
    if not windows:
        return None
    return min(windows, key=_focus_history_id)


def find_window(address: str | None) -> dict[str, Any] | None:
    if not address:
        active = query("activewindow")
        if isinstance(active, dict) and active.get("address"):
            return active
        # hyprbars / taskbar clicks often clear activewindow (layer-shell steal)
        # before the minimize command runs; fall back to focus history.
        return most_recent_managed()
    wanted = normalize_address(address)
    for window in query("clients"):
        if str(window.get("address", "")).lower() == wanted:
            return window
    return None


def is_effectively_focused(window: dict[str, Any], active: dict[str, Any] | None = None) -> bool:
    """True when ``window`` is focused, or was until the shell bar stole focus.

    Clicking Jugoo (layer-shell) clears ``activewindow`` without giving focus to
    another client. Taskbar toggle must still treat that window as focused so
    the second click minimizes instead of only refocusing.
    """
    if active is None:
        active = query("activewindow")
    if not isinstance(active, dict):
        active = {}
    address = window.get("address")
    if not address:
        return False
    if active.get("address") == address:
        return True
    active_address = str(active.get("address") or "")
    if active_address:
        active_window = find_window(active_address)
        if (
            active_window is not None
            and is_managed(active_window)
            and not is_minimized(active_window)
            and active_window.get("class") != SHELL_CLASS
        ):
            return False
    workspace_id = (window.get("workspace") or {}).get("id")
    peers = [
        peer
        for peer in query("clients")
        if is_managed(peer)
        and not is_minimized(peer)
        and (peer.get("workspace") or {}).get("id") == workspace_id
    ]
    if not peers:
        return False
    top = min(peers, key=_focus_history_id)
    return top.get("address") == address


def workspace_target(name: str | None) -> str | None:
    if not isinstance(name, str) or not name or name.startswith("special:"):
        return None
    return name if name.lstrip("-").isdigit() else f"name:{name}"


def goto_workspace(target: str | None) -> list[str]:
    """Switch only when needed (``workspace_back_and_forth`` would bounce back)."""
    if not target or target == workspace_target(query("activeworkspace").get("name")):
        return []
    return [f"workspace {target}"]


def place_commands(window: dict[str, Any], rect: Rect) -> list[str]:
    address = window["address"]
    x, y, width, height = rect
    commands: list[str] = []
    fullscreen = int(window.get("fullscreen") or 0)
    if fullscreen:
        commands += [f"focuswindow address:{address}", f"fullscreen {1 if fullscreen == 1 else 0}"]
    if not window.get("floating"):
        commands.append(f"setfloating address:{address}")
    commands += [
        f"resizewindowpixel exact {width} {height},address:{address}",
        f"movewindowpixel exact {x} {y},address:{address}",
    ]
    return commands


def remember_snap(state: dict[str, Any], window: dict[str, Any], rect: Rect, zone: str) -> None:
    """Keep the pre-snap geometry so dragging out / ``max`` restores it.

    A few dozen pixels of drift still count as "this is the snap we placed",
    so the original size is not overwritten by the snapped size itself.
    """
    address = window["address"]
    current = geometry(window)
    entry = state["snaps"].get(address)
    if entry and near_rect(entry["rect"], current):
        original = entry["orig"]
    else:
        original = list(current)
    state["snaps"][address] = {"orig": list(original), "rect": list(rect), "zone": zone}


def window_area(window: dict[str, Any]) -> Rect:
    return work_area(monitor_by_id(int(window.get("monitor") or 0)))


# ---------------------------------------------------------------- commands


def cmd_snap(zone: str, address: str | None = None) -> None:
    window = find_window(address)
    if window is None or is_minimized(window):
        return
    state = load_state()
    rect = client_rect(zone_rect(zone, window_area(window)), window_bar_height(window))
    remember_snap(state, window, rect, zone)
    save_state(state)
    dispatch(*place_commands(window, rect), f"alterzorder top,address:{window['address']}")


def restore_snap(window: dict[str, Any], state: dict[str, Any]) -> bool:
    entry = state["snaps"].pop(window["address"], None)
    if entry is None:
        return False
    x, y, width, height = entry["orig"]
    ax, ay, aw, ah = window_area(window)
    width, height = min(width, aw), min(height, ah)
    x = max(ax, min(x, ax + aw - width))
    y = max(ay, min(y, ay + ah - height))
    dispatch(*place_commands(window, (x, y, width, height)))
    return True


def is_snapped(window: dict[str, Any], state: dict[str, Any], zone: str | None = None) -> bool:
    entry = state["snaps"].get(window["address"])
    if entry is None or not near_rect(entry["rect"], geometry(window)):
        return False
    return zone is None or entry.get("zone") == zone


def _place_saved(window: dict[str, Any], saved: list[int]) -> None:
    x, y, width, height = saved
    ax, ay, aw, ah = window_area(window)
    width, height = min(width, aw), min(height, ah)
    x = max(ax, min(x, ax + aw - width))
    y = max(ay + window_bar_height(window), min(y, ay + ah - height))
    dispatch(*place_commands(window, (x, y, width, height)))


def cmd_max(address: str | None = None) -> None:
    window = find_window(address)
    if window is None or is_minimized(window):
        return
    state = load_state()
    area = window_area(window)
    bar = window_bar_height(window)
    entry = state["snaps"].get(window["address"])
    current = geometry(window)
    snapped_max = bool(
        entry and entry.get("zone") == "max" and near_rect(entry["rect"], current)
    )
    if fills_work_area(current, area, bar) or snapped_max:
        saved = entry.get("orig") if entry else None
        state["snaps"].pop(window["address"], None)
        save_state(state)
        if saved and not fills_work_area(saved, area, bar):
            _place_saved(window, saved)
        else:
            dispatch(*place_commands(window, default_float(area, bar)))
        return
    cmd_snap("max", window["address"])


def cmd_down(address: str | None = None) -> None:
    window = find_window(address)
    if window is None:
        return
    state = load_state()
    if is_snapped(window, state) and restore_snap(window, state):
        save_state(state)
        return
    cmd_minimize(window["address"])


def cmd_close(address: str | None = None) -> None:
    window = find_window(address)
    if window is not None:
        dispatch(f"closewindow address:{window['address']}")


def _focus_after_minimize(origin: str | None, excluded: str) -> list[str]:
    """Focus the next window on the origin desktop so minimize does not look like a no-op."""
    target = workspace_target(origin)
    excluded = normalize_address(excluded)
    origin_id = None
    if target and target.lstrip("-").isdigit():
        try:
            origin_id = int(target)
        except ValueError:
            origin_id = None
    candidates = [
        window
        for window in query("clients")
        if is_managed(window)
        and not is_minimized(window)
        and normalize_address(str(window.get("address") or "")) != excluded
        and (
            (origin_id is not None and (window.get("workspace") or {}).get("id") == origin_id)
            or (
                origin_id is None
                and workspace_target((window.get("workspace") or {}).get("name")) == target
            )
        )
    ]
    if not candidates:
        return list(goto_workspace(target))
    next_window = min(candidates, key=_focus_history_id)
    return [
        *goto_workspace(target),
        f"focuswindow address:{next_window['address']}",
        f"alterzorder top,address:{next_window['address']}",
    ]


def cmd_minimize(address: str | None = None) -> None:
    window = find_window(address)
    if window is None:
        return
    if is_minimized(window):
        cmd_restore(window["address"])
        return
    if window.get("pinned"):
        notify("no se puede minimizar una ventana fijada")
        return
    origin = (window.get("workspace") or {}).get("name")
    if workspace_target(origin) is None:
        return
    state = load_state()
    state["minimized"] = [
        entry for entry in state["minimized"] if entry.get("address") != window["address"]
    ]
    state["minimized"].append({"address": window["address"], "workspace": origin})
    save_state(state)
    dispatch(
        f"movetoworkspacesilent {MINIMIZED_WS},address:{window['address']}",
        *_close_minimized_overlay(),
        *_focus_after_minimize(origin, window["address"]),
    )


def _close_minimized_overlay() -> list[str]:
    for monitor in query("monitors"):
        if (monitor.get("specialWorkspace") or {}).get("name") == MINIMIZED_WS:
            return ["togglespecialworkspace minimizados"]
    return []


def _restore_commands(address: str, origin: str | None, fallback: str) -> tuple[list[str], str]:
    target = workspace_target(origin) or fallback
    return [f"movetoworkspacesilent {target},address:{address}"], target


def cmd_restore(address: str | None = None) -> None:
    clients = query("clients")
    minimized = {c["address"]: c for c in clients if is_minimized(c)}
    if not minimized:
        return
    state = load_state()
    entries = [e for e in state["minimized"] if e.get("address") in minimized]
    fallback = workspace_target(query("activeworkspace").get("name")) or "1"
    if address:
        address = normalize_address(address)
        if address not in minimized:
            return
    else:
        address = entries[-1]["address"] if entries else next(iter(minimized))
    origin = next((e.get("workspace") for e in entries if e.get("address") == address), None)
    commands, target = _restore_commands(address, origin, fallback)
    state["minimized"] = [e for e in entries if e.get("address") != address]
    save_state(state)
    dispatch(
        *commands,
        *_close_minimized_overlay(),
        *goto_workspace(target),
        f"focuswindow address:{address}",
        f"alterzorder top,address:{address}",
    )


def cmd_restore_all() -> None:
    clients = query("clients")
    minimized = [c["address"] for c in clients if is_minimized(c)]
    if not minimized:
        return
    state = load_state()
    origins = {e.get("address"): e.get("workspace") for e in state["minimized"]}
    fallback = workspace_target(query("activeworkspace").get("name")) or "1"
    commands: list[str] = []
    for address in minimized:
        commands += _restore_commands(address, origins.get(address), fallback)[0]
    state["minimized"] = []
    save_state(state)
    dispatch(*commands, *_close_minimized_overlay())


def cmd_focus(address: str | None = None) -> None:
    """Taskbar semantics: minimized → restore, focused → minimize, else focus."""
    window = find_window(address)
    if window is None:
        return
    if is_minimized(window):
        cmd_restore(window["address"])
        return
    active = query("activewindow")
    active_ws = query("activeworkspace").get("id")
    on_screen = (window.get("workspace") or {}).get("id") == active_ws
    if on_screen and is_effectively_focused(window, active):
        cmd_minimize(window["address"])
        return
    target = workspace_target((window.get("workspace") or {}).get("name"))
    dispatch(
        *goto_workspace(target),
        f"focuswindow address:{window['address']}",
        f"alterzorder top,address:{window['address']}",
    )


def _alt_tab_candidates() -> list[dict[str, Any]]:
    """Mapped windows on the active desktop only, excluding minimized / shell.

    Order is stable across presses: address. Sorting by ``focusHistoryID``
    would reshuffle after every focus and Alt+Tab would only bounce between
    the two most recent windows. Stay on the current desktop so Alt+Tab never
    jumps workspaces (use Super+Left/Right or Ctrl+Alt+PgUp/PgDn for that).
    """
    active_ws = query("activeworkspace").get("id")
    windows = [
        window
        for window in query("clients")
        if is_managed(window)
        and not is_minimized(window)
        and (window.get("workspace") or {}).get("id") == active_ws
        and not str((window.get("workspace") or {}).get("name") or "").startswith("special:")
    ]
    windows.sort(key=lambda c: str(c.get("address") or ""))
    return windows


def _alt_tab_active_index(addresses: list[str]) -> int:
    """Index of the focused window, surviving focus stolen by the Jugoo bar."""
    active = normalize_address((query("activewindow") or {}).get("address"))
    if active:
        try:
            return addresses.index(active)
        except ValueError:
            pass
    recent = most_recent_managed()
    if recent is not None:
        recent_address = normalize_address(recent.get("address"))
        try:
            return addresses.index(recent_address)
        except ValueError:
            pass
    return 0


def cmd_alt_tab(direction: str | None = None) -> None:
    """Cycle windows on the current desktop; raise and focus the next one."""
    windows = _alt_tab_candidates()
    if not windows:
        return
    if len(windows) == 1:
        target = windows[0]
    else:
        addresses = [normalize_address(window["address"]) for window in windows]
        index = _alt_tab_active_index(addresses)
        step = -1 if (direction or "").lower() in {"prev", "previous", "back"} else 1
        target = windows[(index + step) % len(windows)]
    address = target["address"]
    # Do not batch ``bringactivetotop``: in the same [[BATCH]] it can raise the
    # *previous* active window before focuswindow settles, so focus moves to a
    # buried window and it looks like Alt+Tab only stole focus.
    dispatch(
        f"focuswindow address:{address}",
        f"alterzorder top,address:{address}",
    )


def _workspace_windows(address: str | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Managed windows of the target workspace, most recently focused first."""
    anchor = find_window(address) if address else None
    if anchor is not None and is_minimized(anchor):
        cmd_restore(anchor["address"])
        anchor = find_window(anchor["address"])
    workspace_id = (
        (anchor.get("workspace") or {}).get("id")
        if anchor
        else query("activeworkspace").get("id")
    )
    windows = [
        c
        for c in query("clients")
        if is_managed(c)
        and (c.get("workspace") or {}).get("id") == workspace_id
        and not c.get("pinned")
    ]
    windows.sort(key=lambda c: int(c.get("focusHistoryID", 1 << 30)))
    if anchor is not None:
        windows.sort(key=lambda c: c["address"] != anchor["address"])
    return windows, anchor


def _arrange(windows: list[dict[str, Any]], rects: list[Rect], zone: str) -> None:
    if not windows:
        return
    state = load_state()
    commands = goto_workspace(workspace_target((windows[0].get("workspace") or {}).get("name")))
    # Oldest first so the most recent window ends on top.
    for window, rect in reversed(list(zip(windows, rects))):
        target = client_rect(rect, window_bar_height(window))
        remember_snap(state, window, target, zone)
        commands += place_commands(window, target)
        commands.append(f"alterzorder top,address:{window['address']}")
    commands.append(f"focuswindow address:{windows[0]['address']}")
    save_state(state)
    dispatch(*commands)


def cmd_split(count: int, address: str | None = None) -> None:
    windows, _anchor = _workspace_windows(address)
    windows = windows[:count]
    if not windows:
        return
    area = window_area(windows[0])
    n = len(windows)
    if n == 1:
        rects = [zone_rect("max", area)]
    elif n == 2:
        rects = [zone_rect("left", area), zone_rect("right", area)]
    elif n == 3:
        rects = [zone_rect("left", area), zone_rect("top-right", area), zone_rect("bottom-right", area)]
    else:
        rects = [
            zone_rect(zone, area)
            for zone in ("top-left", "top-right", "bottom-left", "bottom-right")
        ]
    _arrange(windows, rects, "layout")


def cmd_grid(address: str | None = None) -> None:
    windows, _anchor = _workspace_windows(address)
    if windows:
        _arrange(windows, grid_rects(len(windows), window_area(windows[0])), "layout")


def cmd_cascade(address: str | None = None) -> None:
    windows, _anchor = _workspace_windows(address)
    if not windows:
        return
    ax, ay, aw, ah = window_area(windows[0])
    width, height = int(aw * 0.62), int(ah * 0.68)
    span_x = max(aw - width - 2 * GAP, 1)
    span_y = max(ah - height - 2 * GAP, 1)
    rects: list[Rect] = []
    # windows[0] is the most recent: it gets the last (front-most) slot.
    for index in range(len(windows)):
        slot = len(windows) - 1 - index
        offset = slot * CASCADE_STEP
        rects.append((ax + GAP + offset % span_x, ay + GAP + offset % span_y, width, height))
    _arrange(windows, rects, "cascade")


# ------------------------------------------------------------ drag & drop


def drop_zone(
    x: int,
    y: int,
    monitor: dict[str, Any],
    window: dict[str, Any] | None = None,
    bar: int = 0,
) -> str | None:
    """Side the pointer (or the window edge under it) hit. None means a free drop.

    Halves are the whole edge. A corner only counts in the last ``CORNER_PX``.
    The top edge maximizes. Touching a side with the window counts too, as long
    as the pointer is still in that half of the screen — that is the Windows
    gesture of pushing the window until it meets the border.
    """
    mx, my, mw, mh = monitor_bounds(monitor)
    _left, top_inset, _right, _bottom = (list(monitor.get("reserved") or []) + [0, 0, 0, 0])[:4]
    at_left = x <= mx + SNAP_MARGIN
    at_right = x >= mx + mw - 1 - SNAP_MARGIN
    at_top = y <= my + max(top_inset, SNAP_MARGIN)
    at_bottom = y >= my + mh - 1 - SNAP_MARGIN
    if window is not None:
        wx, wy, ww, wh = geometry(window)
        if not at_left and wx <= mx + 16 and x < mx + mw * 0.35:
            at_left = True
        if not at_right and wx + ww >= mx + mw - 16 and x > mx + mw * 0.65:
            at_right = True
        visual_top = wy - bar
        if not at_top and visual_top <= my + top_inset + 8 and y < my + mh * 0.25:
            at_top = True
        if not at_bottom and wy + wh >= my + mh - 16 and y > my + mh * 0.75:
            at_bottom = True
    # A window already spanning the screen is not "touching one side".
    if at_left and at_right:
        at_left = at_right = False
    if at_left and y <= my + CORNER_PX:
        return "top-left"
    if at_left and y >= my + mh - CORNER_PX:
        return "bottom-left"
    if at_right and y <= my + CORNER_PX:
        return "top-right"
    if at_right and y >= my + mh - CORNER_PX:
        return "bottom-right"
    if at_left:
        return "left"
    if at_right:
        return "right"
    if at_top:
        return "max"
    return None


def is_true_fullscreen(window: dict[str, Any]) -> bool:
    """Real fullscreen (F11 / games) may cover the Jugoo bar; maximize must not.

    Hyprland reports both fullscreen and maximized as ``fullscreen != 0``.
    Mode ``2`` is maximize. Mode ``1`` that still starts below the reserved
    strip is also treated as maximize so the shell bar stays visible.
    """
    fs = int(window.get("fullscreen") or 0)
    if not fs:
        return False
    if fs == 2:
        return False
    monitor = monitor_by_id(int(window.get("monitor") or 0))
    _mx, my, _mw, mh = monitor_bounds(monitor)
    _x, y, _w, height = geometry(window)
    return y <= my + 2 and height >= mh - 8


def clamp_title_visible(window: dict[str, Any]) -> None:
    """Slide a window down until its title bar clears the shell bar."""
    if not window.get("floating") or is_true_fullscreen(window):
        return
    bar = window_bar_height(window)
    ax, ay, aw, ah = window_area(window)
    x, y, width, height = geometry(window)
    min_y = ay + bar
    new_y = y if y >= min_y else min_y
    max_height = max(80, ay + ah - new_y)
    new_height = height if height <= max_height else max_height
    if new_y == y and new_height == height:
        return
    dispatch(*place_commands(window, (x, new_y, width, new_height)))


def covers_shell_bar(window: dict[str, Any]) -> bool:
    """True when a floating window sits under / over the Jugoo top bar."""
    if not window.get("floating") or is_true_fullscreen(window):
        return False
    monitor = monitor_by_id(int(window.get("monitor") or 0))
    _mx, my, _mw, mh = monitor_bounds(monitor)
    ax, ay, aw, ah = work_area(monitor)
    x, y, width, height = geometry(window)
    bar = window_bar_height(window)
    # Native Hyprland maximize often starts at the monitor top and ignores
    # a healthy exclusive zone after bar-retract collapses it.
    if y <= my + 4 and height >= mh - 24:
        return True
    if y < ay + bar:
        return True
    if y <= ay + 4 and height >= ah - 24:
        return True
    return False


def fit_to_work_area(window: dict[str, Any]) -> None:
    """Place a covering window into the work-area maximize snap."""
    if window is None or is_minimized(window):
        return
    if is_true_fullscreen(window):
        return
    cmd_snap("max", window["address"])


def on_open_window(address: str) -> None:
    """After open: detect CSD chrome and keep the shell bar visible."""
    sync_titlebars()
    window = find_window(normalize_address(address))
    if window is None or not is_managed(window) or is_minimized(window):
        return
    if covers_shell_bar(window) or _AUTO_MAX_CLASS.match(str(window.get("class") or "")):
        fit_to_work_area(window)
        return
    clamp_title_visible(window)


def reveal_covered_windows() -> None:
    for window in query("clients"):
        if not is_managed(window) or is_minimized(window):
            continue
        if covers_shell_bar(window):
            fit_to_work_area(window)
        else:
            clamp_title_visible(window)


def on_drag_end(address: str) -> None:
    window = find_window(address)
    if window is None or not window.get("floating") or is_true_fullscreen(window):
        return
    cursor = query("cursorpos")
    x, y = int(cursor["x"]), int(cursor["y"])
    monitor = monitor_at(x, y)
    zone = drop_zone(x, y, monitor, window, window_bar_height(window))
    if zone is not None:
        cmd_snap(zone, window["address"])
        return
    state = load_state()
    entry = state["snaps"].pop(window["address"], None)
    if entry is not None:
        save_state(state)
    current = geometry(window)
    if entry is not None and near_rect(entry["rect"], current):
        # Dragged out of a snap: restore the original size under the cursor.
        wx, _wy, ww, _wh = current
        width, height = entry["orig"][2], entry["orig"][3]
        ax, ay, aw, ah = work_area(monitor)
        grab = (x - wx) / ww if ww else 0.5
        new_x = max(ax, min(int(x - grab * width), ax + aw - width))
        new_y = max(ay + window_bar_height(window), min(current[1], ay + ah - height))
        dispatch(*place_commands(window, (new_x, new_y, width, height)))
        return
    clamp_title_visible(window)


def forget(address: str) -> None:
    state = load_state()
    address = normalize_address(address)
    changed = state["snaps"].pop(address, None) is not None
    before = len(state["minimized"])
    state["minimized"] = [e for e in state["minimized"] if e.get("address") != address]
    if changed or len(state["minimized"]) != before:
        save_state(state)


# ------------------------------------------------------------------ router


ZONES = ("left", "right", "top-left", "top-right", "bottom-left", "bottom-right")


def run_command(argv: list[str]) -> None:
    if not argv:
        return
    name, address = argv[0], (argv[1] if len(argv) > 1 else None)
    if name in ZONES:
        cmd_snap(name, address)
    elif name == "up":
        cmd_snap("max", address)
    elif name == "max":
        cmd_max(address)
    elif name == "down":
        cmd_down(address)
    elif name == "minimize":
        cmd_minimize(address)
    elif name == "restore":
        cmd_restore(address)
    elif name == "restore-all":
        cmd_restore_all()
    elif name == "focus":
        cmd_focus(address)
    elif name == "alt-tab":
        cmd_alt_tab(address)
    elif name == "close":
        cmd_close(address)
    elif name == "split2":
        cmd_split(2, address)
    elif name == "split4":
        cmd_split(4, address)
    elif name == "grid":
        cmd_grid(address)
    elif name == "cascade":
        cmd_cascade(address)
    else:
        notify(f"comando desconocido '{name}'")


# ------------------------------------------------------------------ daemon


def _daemon_running() -> bool:
    try:
        pid = int(PIDFILE.read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return pid != os.getpid()


def _prepare_fifo() -> int:
    try:
        if not stat.S_ISFIFO(FIFO.lstat().st_mode):
            FIFO.unlink()
    except FileNotFoundError:
        pass
    if not FIFO.exists():
        os.mkfifo(FIFO, 0o600)
    # O_RDWR keeps the FIFO open with no writers, so reads never hit EOF.
    return os.open(FIFO, os.O_RDWR | os.O_NONBLOCK)


def _safe(action, *args) -> None:
    try:
        action(*args)
    except (HyprError, KeyError, TypeError, ValueError, IndexError) as error:
        print(f"ventanas: {error}", file=sys.stderr)


def daemon() -> int:
    if _daemon_running():
        return 0
    PIDFILE.write_text(f"{os.getpid()}\n")
    fifo_fd = _prepare_fifo()
    events = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    events.connect(str(_hypr_dir() / ".socket2.sock"))

    def cleanup(*_args: object) -> None:
        for path in (PIDFILE, FIFO):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    selector = selectors.DefaultSelector()
    selector.register(fifo_fd, selectors.EVENT_READ, "fifo")
    selector.register(events, selectors.EVENT_READ, "events")
    buffers = {"fifo": b"", "events": b""}
    _safe(sync_titlebars)
    _safe(reveal_covered_windows)
    try:
        while True:
            for key, _mask in selector.select():
                source = key.data
                try:
                    chunk = os.read(fifo_fd, 4096) if source == "fifo" else events.recv(65536)
                except BlockingIOError:
                    continue
                if not chunk and source == "events":
                    return 0
                *lines, buffers[source] = (buffers[source] + chunk).split(b"\n")
                for raw in lines:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    if source == "fifo":
                        _safe(run_command, line.split())
                        continue
                    event, _sep, data = line.partition(">>")
                    if event == "hyprbarsdragend":
                        _safe(on_drag_end, data)
                    elif event == "openwindow":
                        address = data.split(",", 1)[0]
                        _safe(on_open_window, address)
                    elif event == "closewindow":
                        _safe(forget, data)
                    elif event == "fullscreen":
                        # Maximize must stay under Jugoo; only true fullscreen covers it.
                        _safe(reveal_covered_windows)
                    elif event in ("movewindow", "movewindowv2", "changefloatingmode"):
                        _safe(reveal_covered_windows)
    finally:
        cleanup()


def main(argv: list[str]) -> int:
    if argv[:1] == ["daemon"]:
        return daemon()
    try:
        run_command(argv)
    except HyprError as error:
        notify(str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
