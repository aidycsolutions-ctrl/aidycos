"""Bar panel popups: single-section views and the full control center."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk

from ..eventbus import EventBus
from ..popup_handle import PopupHandle, PopupOutsideDismiss
from ..servicios.bluetooth.service import (
    BLUETOOTH_CHANGED,
    BLUETOOTH_CLICKED,
    BluetoothService,
)
from ..servicios.red.network import NETWORK_CHANGED, NETWORK_ETHERNET_CLICKED, NetworkService
from ..widgets.barra.bluetooth import BluetoothWidget
from ..widgets.barra.ethernet import EthernetWidget
from ..widgets.barra.power import POWER_CONTROL_CENTER_REQUESTED, PowerWidget
from ..widgets.centro_control.popup import ControlCenterPopup
from ..widgets.centro_control.views import ControlCenterView


class ControlCenterController:
    """Opens section-specific panels and the full control center from the bar."""

    def __init__(
        self,
        event_bus: EventBus,
        network_service: NetworkService,
        ethernet_widget: EthernetWidget,
        power_widget: PowerWidget,
        shell_window: Gtk.Window,
        *,
        bluetooth_service: BluetoothService | None = None,
        bluetooth_widget: BluetoothWidget | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._service = network_service
        self._bluetooth_service = bluetooth_service
        self._ethernet_widget = ethernet_widget
        self._bluetooth_widget = bluetooth_widget
        self._power_widget = power_widget
        self._shell_window = shell_window
        self._outside_click = PopupOutsideDismiss()

        def _make_popup(view: ControlCenterView) -> ControlCenterPopup:
            kwargs = {"view": view}
            # Newer overlay popup accepts bluetooth_service=; older ones ignore via TypeError.
            try:
                return ControlCenterPopup(
                    shell_window,
                    network_service,
                    bluetooth_service=bluetooth_service,
                    **kwargs,
                )
            except TypeError:
                return ControlCenterPopup(shell_window, network_service, **kwargs)

        self._network_panel = PopupHandle(lambda: _make_popup(ControlCenterView.NETWORK))
        self._bluetooth_panel = PopupHandle(
            lambda: _make_popup(
                ControlCenterView.BLUETOOTH
                if hasattr(ControlCenterView, "BLUETOOTH")
                else ControlCenterView.NETWORK
            ),
        )
        self._full_center = PopupHandle(lambda: _make_popup(ControlCenterView.FULL))
        self._active_panel: PopupHandle | None = None
        self._active_anchor: Gtk.Widget | None = None

        self._event_bus.subscribe(NETWORK_ETHERNET_CLICKED, self._on_network_panel_requested)
        self._event_bus.subscribe(BLUETOOTH_CLICKED, self._on_bluetooth_panel_requested)
        self._event_bus.subscribe(
            POWER_CONTROL_CENTER_REQUESTED,
            self._on_full_control_center_requested,
        )
        self._event_bus.subscribe(NETWORK_CHANGED, self._on_network_changed)
        self._event_bus.subscribe(BLUETOOTH_CHANGED, self._on_bluetooth_changed)

    def close_popup(self) -> None:
        self._outside_click.uninstall()
        for handle in (self._network_panel, self._bluetooth_panel, self._full_center):
            popup = handle.maybe
            if popup is not None:
                popup.close_popup()
        self._active_panel = None
        self._active_anchor = None

    def toggle_network_panel(self) -> None:
        self._toggle_panel(self._network_panel, self._ethernet_widget.get_anchor_button())

    def toggle_bluetooth_panel(self) -> None:
        anchor = (
            self._bluetooth_widget.get_anchor_button()
            if self._bluetooth_widget is not None
            else self._ethernet_widget.get_anchor_button()
        )
        self._toggle_panel(self._bluetooth_panel, anchor)

    def toggle_full_control_center(self) -> None:
        self._power_widget.close_menu()
        self._toggle_panel(self._full_center, self._power_widget.get_anchor_button())

    def _toggle_panel(self, handle: PopupHandle, anchor: Gtk.Widget) -> None:
        if handle.is_visible() and self._active_panel is handle:
            self.close_popup()
            return
        self._open_panel(handle, anchor)

    def _open_panel(self, handle: PopupHandle, anchor: Gtk.Widget) -> None:
        if self._active_panel is not handle:
            self.close_popup()
        popup = handle.get()
        self._active_panel = handle
        self._active_anchor = anchor
        popup.open_for(anchor)
        self._outside_click.install(
            popup,
            self._shell_window,
            (anchor,),
            self.close_popup,
            self._event_bus,
        )

    def _on_network_panel_requested(self, _ethernet) -> None:
        GLib.idle_add(self._handle_network_panel_requested)

    def _handle_network_panel_requested(self) -> bool:
        self.toggle_network_panel()
        return False

    def _on_bluetooth_panel_requested(self, _snapshot) -> None:
        GLib.idle_add(self._handle_bluetooth_panel_requested)

    def _handle_bluetooth_panel_requested(self) -> bool:
        self.toggle_bluetooth_panel()
        return False

    def _on_full_control_center_requested(self, _anchor_button) -> None:
        GLib.idle_add(self._handle_full_control_center_requested)

    def _handle_full_control_center_requested(self) -> bool:
        self.toggle_full_control_center()
        return False

    def _on_network_changed(self, _snapshot) -> None:
        GLib.idle_add(self._refresh_visible_popups)

    def _on_bluetooth_changed(self, _snapshot) -> None:
        GLib.idle_add(self._refresh_visible_popups)

    def _refresh_visible_popups(self) -> bool:
        for handle in (self._network_panel, self._bluetooth_panel, self._full_center):
            popup = handle.maybe
            if popup is not None and popup.get_visible():
                popup.refresh()
        return False
