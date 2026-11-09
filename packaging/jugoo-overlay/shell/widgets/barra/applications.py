"""Bar button that opens the application launcher (same as Super+Space)."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk

from ...config import PINNED_APP_ICON_SIZE
from ...ui import ShellModule

ToggleLauncher = Callable[[], None]


class ApplicationsMenuWidget(ShellModule):
    """Grid button on the bar to open the searchable app drawer without shortcuts."""

    def __init__(self, on_toggle: ToggleLauncher) -> None:
        super().__init__("applications-menu-widget", spacing=0)
        self._on_toggle = on_toggle

        self._button = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        self._button.get_style_context().add_class("applications-menu-button")
        self._button.set_tooltip_text("Aplicaciones")
        icon = Gtk.Image.new_from_icon_name("view-app-grid-symbolic", Gtk.IconSize.DIALOG)
        icon.set_pixel_size(PINNED_APP_ICON_SIZE)
        icon.get_style_context().add_class("applications-menu-icon")
        self._button.set_image(icon)
        self._button.set_always_show_image(True)
        self._button.connect("clicked", self._on_clicked)
        self.pack_start(self._button, False, False, 0)

    def _on_clicked(self, *_args) -> None:
        self._on_toggle()
