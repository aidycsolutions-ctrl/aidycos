"""Desktop notifications via FreeDesktop Notifications (Jugoo host)."""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

from .paths import runtime_dir

LOGGER = logging.getLogger(__name__)

# Coalesce noisy chat pops: replace previous bubble instead of stacking.
_LOCK = threading.Lock()
_LAST_KEY = ""
_LAST_AT = 0.0
_REPLACE_ID = 0
_THROTTLE_S = 8.0


def ui_raise_socket_path() -> Path:
    return runtime_dir() / "aidylink-ui.sock"


def notify(
    title: str,
    body: str,
    *,
    urgency: str = "normal",
    kind: str = "message",
) -> None:
    """Show a desktop notification with throttling.

    ``kind``:
      - ``message``: coalesced / rate-limited chat alerts
      - ``status``: suppressed by default (startup/online noise)
      - ``important``: pairing / approvals (always shown, not throttled hard)
    """
    title = (title or "AidyChat")[:80]
    body = (body or "")[:240]
    if kind == "status":
        LOGGER.info("notify(status suppressed): %s — %s", title, body)
        return

    global _LAST_KEY, _LAST_AT, _REPLACE_ID
    key = f"{kind}|{title}|{body}"
    now = time.time()
    replace_id = 0
    with _LOCK:
        if kind == "message":
            # Same text within the window: skip entirely.
            if key == _LAST_KEY and (now - _LAST_AT) < _THROTTLE_S:
                return
            # Same sender/title within the window: replace previous bubble.
            if (
                _LAST_KEY.startswith(f"{kind}|{title}|")
                and (now - _LAST_AT) < _THROTTLE_S
                and _REPLACE_ID
            ):
                replace_id = _REPLACE_ID
            _LAST_KEY = key
            _LAST_AT = now

    # Chat alerts use replace-id (no --wait). Pairing keeps an Abrir action
    # that focuses the existing window instead of spawning another process.
    printed_id = _notify_send(
        title,
        body,
        urgency=urgency,
        replace_id=replace_id,
        with_action=(kind == "important"),
        action_label="Abrir AidyChat",
    )
    if printed_id:
        with _LOCK:
            _REPLACE_ID = printed_id
            _LAST_KEY = key
            _LAST_AT = now
        return
    if _gdbus(title, body, replace_id=replace_id):
        return
    LOGGER.info("notify: %s — %s", title, body)


def raise_or_open_ui() -> bool:
    """Focus an existing AidyChat window; only launch a new one if needed."""
    if _raise_existing_ui():
        return True
    return _spawn_ui()


def claim_ui_instance() -> "UiRaiseServer | None":
    """Claim the single UI raise socket.

    Returns a server to ``attach(window)`` when this process owns the UI.
    Returns ``None`` when another AidyChat window was raised (exit early).
    """
    if _raise_existing_ui():
        return None
    server = UiRaiseServer()
    if not server.bind():
        # Lost the race — ask the winner to raise.
        if _raise_existing_ui():
            return None
        # Fall through and run without the socket (still better than failing).
        return server
    return server


class UiRaiseServer:
    """Unix socket so notification clicks focus this window instead of spawning."""

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._window: object | None = None
        self._stop = threading.Event()

    def bind(self) -> bool:
        path = ui_raise_socket_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                return False
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(path))
            sock.listen(4)
            sock.settimeout(0.5)
        except OSError:
            LOGGER.debug("could not bind ui raise socket", exc_info=True)
            return False
        self._sock = sock
        self._thread = threading.Thread(
            target=self._serve,
            name="aidychat-ui-raise",
            daemon=True,
        )
        self._thread.start()
        return True

    def attach(self, window: object) -> None:
        self._window = window

    def close(self) -> None:
        self._stop.set()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        path = ui_raise_socket_path()
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    def _serve(self) -> None:
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                break
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                with conn:
                    conn.settimeout(0.5)
                    try:
                        data = conn.recv(64)
                    except OSError:
                        data = b""
                    if b"raise" in data:
                        self._request_raise()
                    try:
                        conn.sendall(b"ok\n")
                    except OSError:
                        pass
            except OSError:
                continue

    def _request_raise(self) -> None:
        window = self._window
        if window is None:
            return
        try:
            from gi.repository import GLib  # type: ignore

            def _present() -> bool:
                try:
                    present = getattr(window, "present", None)
                    if callable(present):
                        present()
                    deiconify = getattr(window, "deiconify", None)
                    if callable(deiconify):
                        deiconify()
                except Exception:
                    LOGGER.debug("present window failed", exc_info=True)
                return False

            GLib.idle_add(_present)
        except Exception:
            LOGGER.debug("GLib raise failed", exc_info=True)


def _raise_existing_ui() -> bool:
    sock_path = ui_raise_socket_path()
    if not sock_path.exists():
        return _raise_via_wm()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.6)
            sock.connect(str(sock_path))
            sock.sendall(b"raise\n")
            try:
                reply = sock.recv(16)
            except OSError:
                reply = b""
        # Only treat an explicit ACK as success. An empty reply used to mean
        # “raised” and made AidyChat exit without opening when the socket was stale.
        if reply.startswith(b"ok"):
            return True
    except OSError:
        LOGGER.debug("ui raise socket failed", exc_info=True)
    try:
        sock_path.unlink(missing_ok=True)
    except OSError:
        pass
    return _raise_via_wm()


def _raise_via_wm() -> bool:
    """Best-effort focus by window title when the raise socket is missing."""
    # Hyprland / Wayland first (wmctrl is X11-only and often no-ops here).
    if shutil.which("hyprctl"):
        for arg in (
            "class:^(aidychat)$",
            "title:^(AidyChat)(.*)$",
            "title:^(AidyLink)(.*)$",
        ):
            try:
                completed = subprocess.run(
                    ["hyprctl", "dispatch", "focuswindow", arg],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                    check=False,
                )
                if completed.returncode == 0:
                    return True
            except (OSError, subprocess.TimeoutExpired):
                continue
    for cmd in (
        ["wmctrl", "-a", "AidyChat"],
        ["xdotool", "search", "--name", "AidyChat", "windowactivate", "--sync"],
    ):
        if not shutil.which(cmd[0]):
            continue
        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
            if completed.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def _aidylink_bin() -> str:
    local = Path.home() / ".local" / "bin" / "aidylink"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    which = shutil.which("aidylink")
    if which:
        return which
    return "/usr/local/bin/aidylink"


def _spawn_ui() -> bool:
    binary = _aidylink_bin()
    try:
        subprocess.Popen(
            [binary, "ui"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=os.environ.copy(),
        )
        return True
    except OSError:
        LOGGER.debug("could not spawn AidyChat UI", exc_info=True)
        return False


def _notify_send(
    title: str,
    body: str,
    *,
    urgency: str,
    replace_id: int = 0,
    with_action: bool = False,
    action_label: str = "Abrir",
) -> int:
    binary = shutil.which("notify-send")
    if not binary:
        return 0
    cmd = [
        binary,
        "-a",
        "AidyChat",
        "-u",
        urgency,
        "-i",
        "aidychat",
        "-h",
        "string:desktop-entry:aidychat",
        "-e",
        "-t",
        "5000",
    ]
    if replace_id:
        cmd.extend(["-r", str(replace_id)])
    # -A implies --wait. Click runs raise_or_open_ui (focus existing first).
    if with_action:
        cmd.extend(["-A", f"open={action_label}"])
    else:
        cmd.append("-p")
    cmd.extend([title, body])
    try:
        if with_action:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            threading.Thread(
                target=_open_on_action,
                args=(proc,),
                daemon=True,
                name="aidychat-notify-action",
            ).start()
            return replace_id or 1
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        text = (out or b"").decode("utf-8", errors="replace").strip()
        return int(text) if text.isdigit() else 1
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
        return 0


def _open_on_action(proc: subprocess.Popen[bytes]) -> None:
    try:
        raw = proc.communicate(timeout=120)[0] or b""
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
        except OSError:
            pass
        return
    if raw.strip() == b"open":
        raise_or_open_ui()


def _gdbus(title: str, body: str, *, replace_id: int = 0) -> bool:
    binary = shutil.which("gdbus")
    if not binary:
        return False
    try:
        subprocess.run(
            [
                binary,
                "call",
                "--session",
                "--dest",
                "org.freedesktop.Notifications",
                "--object-path",
                "/org/freedesktop/Notifications",
                "--method",
                "org.freedesktop.Notifications.Notify",
                "AidyChat",
                str(int(replace_id or 0)),
                "aidychat",
                title,
                body,
                "[]",
                '{"desktop-entry": <"aidychat">, "transient": <true>}',
                "5000",
            ],
            check=False,
            timeout=3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False
