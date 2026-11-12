"""Bar edge placement for the Jugoo layer-shell strip (AidyCOS)."""

from __future__ import annotations

from typing import Iterable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gtk, GtkLayerShell

from . import config as shell_config

BAR_POSITIONS = ("top", "bottom", "left", "right")
DEFAULT_BAR_POSITION = "top"

_EDGE = {
    "top": GtkLayerShell.Edge.TOP,
    "bottom": GtkLayerShell.Edge.BOTTOM,
    "left": GtkLayerShell.Edge.LEFT,
    "right": GtkLayerShell.Edge.RIGHT,
}


def normalize_bar_position(value: object | None = None) -> str:
    """Return a known edge name; unknown values fall back to top."""
    if value is None:
        value = getattr(shell_config, "BAR_POSITION", DEFAULT_BAR_POSITION)
    text = str(value).strip().casefold()
    return text if text in BAR_POSITIONS else DEFAULT_BAR_POSITION


def is_vertical_bar(position: object | None = None) -> bool:
    return normalize_bar_position(position) in ("left", "right")


def bar_primary_edge(position: object | None = None) -> GtkLayerShell.Edge:
    return _EDGE[normalize_bar_position(position)]


def bar_anchor_edges(position: object | None = None) -> tuple[GtkLayerShell.Edge, ...]:
    """Layer-shell anchors that stretch the bar along the chosen edge."""
    pos = normalize_bar_position(position)
    if pos == "top":
        return (
            GtkLayerShell.Edge.TOP,
            GtkLayerShell.Edge.LEFT,
            GtkLayerShell.Edge.RIGHT,
        )
    if pos == "bottom":
        return (
            GtkLayerShell.Edge.BOTTOM,
            GtkLayerShell.Edge.LEFT,
            GtkLayerShell.Edge.RIGHT,
        )
    if pos == "left":
        return (
            GtkLayerShell.Edge.LEFT,
            GtkLayerShell.Edge.TOP,
            GtkLayerShell.Edge.BOTTOM,
        )
    return (
        GtkLayerShell.Edge.RIGHT,
        GtkLayerShell.Edge.TOP,
        GtkLayerShell.Edge.BOTTOM,
    )


def configure_bar_layer_shell(
    window: Gtk.Window,
    *,
    position: object | None = None,
    margin: int | None = None,
) -> None:
    """Anchor the shell strip to the configured monitor edge."""
    pos = normalize_bar_position(position)
    inset = int(shell_config.TOP_MARGIN if margin is None else margin)
    primary = bar_primary_edge(pos)
    wanted = set(bar_anchor_edges(pos))

    for edge in (
        GtkLayerShell.Edge.TOP,
        GtkLayerShell.Edge.BOTTOM,
        GtkLayerShell.Edge.LEFT,
        GtkLayerShell.Edge.RIGHT,
    ):
        GtkLayerShell.set_anchor(window, edge, edge in wanted)
        GtkLayerShell.set_margin(window, edge, inset if edge == primary else 0)


def apply_bar_size_requests(
    widgets: Iterable[Gtk.Widget],
    monitor,
    *,
    position: object | None = None,
) -> None:
    """Stretch the bar along the screen edge for the active position."""
    if monitor is None:
        return
    geometry = monitor.get_geometry()
    pos = normalize_bar_position(position)
    if is_vertical_bar(pos):
        width, height = -1, int(geometry.height)
    else:
        width, height = int(geometry.width), -1
    for widget in widgets:
        widget.set_size_request(width, height)


def apply_bar_expand_flags(widget: Gtk.Widget, *, position: object | None = None) -> None:
    """Match GTK expand axes to horizontal vs vertical bars."""
    vertical = is_vertical_bar(position)
    widget.set_hexpand(not vertical)
    widget.set_halign(Gtk.Align.FILL if not vertical else Gtk.Align.START)
    widget.set_vexpand(vertical)
    widget.set_valign(Gtk.Align.FILL if vertical else Gtk.Align.START)


def exclusive_zone_size(shell: Gtk.Window, *, position: object | None = None) -> int:
    """Pixels reserved by the compositor for the bar exclusive zone."""
    if is_vertical_bar(position):
        return max(1, int(shell.get_allocated_width()))
    return max(1, int(shell.get_allocated_height()))


def compute_popup_for_bar(
    *,
    button_left: int,
    button_top: int,
    button_width: int,
    button_height: int,
    popup_width: int,
    popup_height: int,
    offset: int,
    fixed_top: int | None = None,
    monitor=None,
    margin: int | None = None,
    position: object | None = None,
) -> tuple[int, int]:
    """Place a popup beside the bar instead of always below the anchor."""
    edge = shell_config.POPUP_EDGE_MARGIN if margin is None else margin
    pos = normalize_bar_position(position)
    center_x = button_left + button_width // 2
    center_y = button_top + button_height // 2
    button_right = button_left + button_width
    button_bottom = button_top + button_height

    if pos == "bottom":
        popup_left = center_x - popup_width // 2
        popup_top = (
            fixed_top
            if fixed_top is not None
            else button_top - popup_height - offset
        )
    elif pos == "left":
        popup_left = button_right + offset
        popup_top = center_y - popup_height // 2
    elif pos == "right":
        popup_left = button_left - popup_width - offset
        popup_top = center_y - popup_height // 2
    else:
        popup_left = center_x - popup_width // 2
        popup_top = fixed_top if fixed_top is not None else button_bottom + offset

    if monitor is not None:
        mon_left = int(monitor.x)
        mon_top = int(monitor.y)
        mon_right = int(monitor.x + monitor.width)
        mon_bottom = int(monitor.y + monitor.height)

        popup_left = max(
            mon_left + edge,
            min(popup_left, mon_right - popup_width - edge),
        )
        if pos == "bottom":
            # Keep the popup above the bar; clamp only against the top edge.
            popup_top = min(popup_top, mon_bottom - popup_height - edge)
            popup_top = max(mon_top + edge, popup_top)
        elif pos in ("left", "right"):
            popup_top = max(
                mon_top + edge,
                min(popup_top, mon_bottom - popup_height - edge),
            )
        else:
            # Top bar: never slide upward into the strip.
            popup_top = max(mon_top + edge, popup_top)

    return int(popup_left), int(popup_top)
