"""Compact Bluetooth indicator driven by BluetoothService snapshots."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk

from ...config import NETWORK_ICON_SIZE
from ...eventbus import EventBus
from ...models import BluetoothSnapshot
from ...servicios.bluetooth.service import (
    BLUETOOTH_CHANGED,
    BLUETOOTH_CLICKED,
    BluetoothService,
    bluetooth_bar_icon_name,
    bluetooth_bar_tooltip,
)
from ...ui import ShellModule


class BluetoothWidget(ShellModule):
    """Bar indicator for Bluetooth; left click opens the Bluetooth panel."""

    def __init__(
        self,
        event_bus: EventBus,
        bluetooth_service: BluetoothService,
    ) -> None:
        super().__init__("bluetooth-widget", spacing=0)

        self._event_bus = event_bus
        self._service = bluetooth_service
        self._snapshot = bluetooth_service.snapshot

        self._button = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        self._button.get_style_context().add_class("bluetooth-button")
        self._button.connect("button-press-event", self._on_button_press)

        self._icon = Gtk.Image.new_from_icon_name(
            "bluetooth-symbolic",
            Gtk.IconSize.MENU,
        )
        self._icon.get_style_context().add_class("bluetooth-icon")
        self._icon.set_pixel_size(NETWORK_ICON_SIZE)
        self._button.add(self._icon)
        self.pack_start(self._button, False, False, 0)

        self._event_bus.subscribe(BLUETOOTH_CHANGED, self._on_bluetooth_changed)
        self.connect("destroy", self._on_destroy)
        GLib.idle_add(self._apply_snapshot, self._snapshot)

    def get_anchor_button(self) -> Gtk.Widget:
        return self._button

    def _on_destroy(self, *_args) -> None:
        self._event_bus.unsubscribe(BLUETOOTH_CHANGED, self._on_bluetooth_changed)

    def _on_bluetooth_changed(self, snapshot: BluetoothSnapshot) -> None:
        GLib.idle_add(self._apply_snapshot, snapshot)

    def _apply_snapshot(self, snapshot: BluetoothSnapshot) -> bool:
        self._snapshot = snapshot
        self._icon.set_from_icon_name(bluetooth_bar_icon_name(snapshot), Gtk.IconSize.MENU)
        self._icon.set_pixel_size(NETWORK_ICON_SIZE)
        self._button.set_tooltip_text(bluetooth_bar_tooltip(snapshot))
        self.show_all()
        return False

    def _on_button_press(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        if event.button == 1:
            self._event_bus.emit(BLUETOOTH_CLICKED, self._snapshot)
            return True
        if event.button == 3:
            # Right click toggles power like Ethernet toggles link.
            if self._snapshot.available:
                self._service.set_powered(not self._snapshot.powered)
            return True
        return False
