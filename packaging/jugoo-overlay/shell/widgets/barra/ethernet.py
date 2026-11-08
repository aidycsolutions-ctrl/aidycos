"""Compact network indicator with a Wi-Fi glyph when wireless is available."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk

from ...config import NETWORK_ICON_SIZE
from ...eventbus import EventBus
from ...models import NetworkSnapshot
from ...servicios.red.network import (
    NETWORK_CHANGED,
    NETWORK_ETHERNET_CLICKED,
    NetworkService,
    ethernet_icon_name,
    ethernet_visual_state,
)
from ...ui import ShellModule


class EthernetWidget(ShellModule):
    """Bar button that opens network settings and shows Wi-Fi when available."""

    def __init__(self, event_bus: EventBus, network_service: NetworkService) -> None:
        super().__init__("ethernet-widget", spacing=0)
        self._event_bus = event_bus
        self._service = network_service
        self._snapshot = network_service.snapshot
        self._button = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        self._button.get_style_context().add_class("ethernet-button")
        self._button.connect("button-press-event", self._on_button_press)
        self._icon = Gtk.Image.new_from_icon_name(
            "network-wireless-symbolic", Gtk.IconSize.MENU
        )
        self._icon.get_style_context().add_class("ethernet-icon")
        self._icon.set_pixel_size(NETWORK_ICON_SIZE)
        self._button.add(self._icon)
        self.pack_start(self._button, False, False, 0)
        self._event_bus.subscribe(NETWORK_CHANGED, self._on_network_changed)
        self.connect("destroy", self._on_destroy)
        GLib.idle_add(self._apply_snapshot, self._snapshot)

    def get_anchor_button(self) -> Gtk.Widget:
        return self._button

    def _on_destroy(self, *_args) -> None:
        self._event_bus.unsubscribe(NETWORK_CHANGED, self._on_network_changed)

    def _on_network_changed(self, snapshot: NetworkSnapshot) -> None:
        GLib.idle_add(self._apply_snapshot, snapshot)

    def _apply_snapshot(self, snapshot: NetworkSnapshot) -> bool:
        self._snapshot = snapshot
        wifi = snapshot.wifi
        if wifi is not None:
            icon_name = "network-wireless-symbolic"
            state = wifi.state
            if not snapshot.wireless_enabled or not snapshot.wireless_hardware_enabled:
                label = "Wi-Fi desactivado"
                visual_state = "unavailable"
            elif state in {"connecting", "disconnecting"}:
                label = "Conectando a Wi-Fi…"
                visual_state = "connecting"
            elif wifi.connected:
                label = f"Wi-Fi: {wifi.connection_name or wifi.interface}"
                visual_state = "connected" if snapshot.connectivity.has_internet else "no-internet"
            else:
                label = "Wi-Fi: sin conexión"
                visual_state = "disconnected"
        else:
            icon_name = ethernet_icon_name(snapshot)
            if icon_name is None:
                self.hide()
                return False
            label = "Red cableada"
            visual_state = ethernet_visual_state(snapshot) or ""

        self._icon.set_from_icon_name(icon_name, Gtk.IconSize.MENU)
        self._icon.set_pixel_size(NETWORK_ICON_SIZE)
        self._button.set_tooltip_text(label)
        style = self._button.get_style_context()
        for name in ("connected", "connecting", "unavailable", "no-internet", "disconnected"):
            style.remove_class(f"ethernet-state-{name}")
        if visual_state:
            style.add_class(f"ethernet-state-{visual_state}")
        self.show_all()
        return False

    def _on_button_press(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        if event.button in (1, 3):
            self._event_bus.emit(NETWORK_ETHERNET_CLICKED, self._snapshot.primary)
            return True
        return False
