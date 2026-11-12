"""GTK layout primitives for placing shell modules in named regions."""

from __future__ import annotations

from typing import Iterator

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk

from .bar_position import is_vertical_bar, normalize_bar_position
from .ui.tokens import SHELL_BAR_MODULE_SPACING, SHELL_BAR_REGION_SPACING

SHELL_BAR_CLASS = "shell-bar"


class ShellRegion(Gtk.Box):
    """A region owns its module ordering, so callers never need GTK packing APIs."""

    def __init__(self, name: str, *, orientation: Gtk.Orientation) -> None:
        super().__init__(orientation=orientation)
        self.set_name(name)
        self.set_spacing(SHELL_BAR_MODULE_SPACING)

    def add(self, widget: Gtk.Widget) -> None:
        """Append a module using the region's standard natural-size packing."""
        self.pack_start(widget, False, False, 0)

    def remove(self, widget: Gtk.Widget) -> None:
        """Detach a module that belongs to this region."""
        Gtk.Box.remove(self, widget)

    def __iter__(self) -> Iterator[Gtk.Widget]:
        return iter(self.get_children())


class LeftContainer(ShellRegion):
    def __init__(self, *, orientation: Gtk.Orientation) -> None:
        super().__init__("shell-left", orientation=orientation)


class CenterContainer(ShellRegion):
    def __init__(self, *, orientation: Gtk.Orientation) -> None:
        super().__init__("shell-center", orientation=orientation)


class RightContainer(ShellRegion):
    def __init__(self, *, orientation: Gtk.Orientation) -> None:
        super().__init__("shell-right", orientation=orientation)


def _flex_slot(*, vertical: bool) -> Gtk.Box:
    """Empty expanding slot so start/end regions pin to the screen edges."""
    orientation = Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL
    slot = Gtk.Box(orientation=orientation)
    if vertical:
        slot.set_vexpand(True)
        slot.set_valign(Gtk.Align.FILL)
        slot.set_hexpand(False)
    else:
        slot.set_hexpand(True)
        slot.set_halign(Gtk.Align.FILL)
        slot.set_vexpand(False)
    return slot


class ShellLayout(Gtk.Box):
    """Root bar container: one outer capsule wrapping left/center/right regions."""

    def __init__(self) -> None:
        vertical = is_vertical_bar()
        orientation = (
            Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL
        )
        super().__init__(orientation=orientation)
        self.position = normalize_bar_position()
        self.get_style_context().add_class(SHELL_BAR_CLASS)
        if vertical:
            self.get_style_context().add_class("shell-bar-vertical")
        self.set_hexpand(not vertical)
        self.set_halign(Gtk.Align.FILL if not vertical else Gtk.Align.START)
        self.set_vexpand(vertical)
        self.set_valign(Gtk.Align.FILL if vertical else Gtk.Align.START)
        self.set_spacing(SHELL_BAR_REGION_SPACING)
        self.left = LeftContainer(orientation=orientation)
        self.center = CenterContainer(orientation=orientation)
        self.right = RightContainer(orientation=orientation)

        # Pin edges with flex slots. Giving the center region expand=True does
        # not consume leftover width here: CenterContainer reports no hexpand
        # (its child is packed non-expanding), so GTK treats the three regions
        # as a centered group and leaves a large gutter on the left.
        if vertical:
            self.left.set_vexpand(False)
            self.left.set_valign(Gtk.Align.START)
            self.center.set_vexpand(False)
            self.center.set_valign(Gtk.Align.CENTER)
            self.right.set_vexpand(False)
            self.right.set_valign(Gtk.Align.END)
        else:
            self.left.set_hexpand(False)
            self.left.set_halign(Gtk.Align.START)
            self.center.set_hexpand(False)
            self.center.set_halign(Gtk.Align.CENTER)
            self.right.set_hexpand(False)
            self.right.set_halign(Gtk.Align.END)

        self.pack_start(self.left, False, False, 0)
        self.pack_start(_flex_slot(vertical=vertical), True, True, 0)
        self.pack_start(self.center, False, False, 0)
        self.pack_start(_flex_slot(vertical=vertical), True, True, 0)
        self.pack_start(self.right, False, False, 0)
