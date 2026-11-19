"""Bluetooth section for the control center (BlueZ)."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk

from ...models import BluetoothDeviceSnapshot, BluetoothSnapshot
from ...servicios.bluetooth.service import device_display_name
from ...ui import ShellModule


class ControlCenterBluetoothSection(ShellModule):
    """Power toggle, discovery and device list backed by BluetoothService."""

    def __init__(
        self,
        *,
        on_toggle_powered: Callable[[bool], None],
        on_request_discovery: Callable[[], None],
        on_connect: Callable[[str], None],
        on_disconnect: Callable[[str], None],
        on_forget: Callable[[str], None],
    ) -> None:
        super().__init__("control-center-bluetooth-section", spacing=0)
        self._on_toggle_powered = on_toggle_powered
        self._on_request_discovery = on_request_discovery
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_forget = on_forget

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.get_style_context().add_class("control-center-section")
        self.pack_start(outer, True, True, 0)

        title = Gtk.Label(xalign=0)
        title.get_style_context().add_class("control-center-section-title")
        title.set_markup("<b>Bluetooth</b>")
        outer.pack_start(title, False, False, 0)

        outer.pack_start(self._build_block(), False, False, 0)

    def refresh(self, snapshot: BluetoothSnapshot) -> None:
        self._wifi_style_sync(snapshot)

    def _build_block(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.get_style_context().add_class("control-center-subsection")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        heading = Gtk.Label(label="Adaptador", xalign=0)
        heading.get_style_context().add_class("control-center-subsection-title")
        heading.set_hexpand(True)
        header.pack_start(heading, True, True, 0)

        self._power_switch = Gtk.Switch()
        self._power_switch.set_halign(Gtk.Align.END)
        self._power_switch.connect("notify::active", self._on_power_switch_changed)
        header.pack_start(self._power_switch, False, False, 0)
        box.pack_start(header, False, False, 0)

        self._status = Gtk.Label(xalign=0)
        self._status.get_style_context().add_class("control-center-detail")
        box.pack_start(self._status, False, False, 0)

        self._error = Gtk.Label(xalign=0)
        self._error.get_style_context().add_class("control-center-detail-muted")
        self._error.set_line_wrap(True)
        box.pack_start(self._error, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions.set_halign(Gtk.Align.END)
        self._scan_button = Gtk.Button(label="Buscar dispositivos", relief=Gtk.ReliefStyle.NONE)
        self._scan_button.get_style_context().add_class("control-center-action")
        self._scan_button.connect("clicked", lambda *_args: self._on_request_discovery())
        actions.pack_start(self._scan_button, False, False, 0)
        box.pack_start(actions, False, False, 0)

        self._device_list = Gtk.ListBox()
        self._device_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._device_list.get_style_context().add_class("control-center-wifi-list")
        box.pack_start(self._device_list, False, False, 0)
        return box

    def _on_power_switch_changed(self, switch: Gtk.Switch, _pspec) -> None:
        self._on_toggle_powered(bool(switch.get_active()))

    def _wifi_style_sync(self, snapshot: BluetoothSnapshot) -> None:
        self._power_switch.handler_block_by_func(self._on_power_switch_changed)
        self._power_switch.set_sensitive(snapshot.available)
        self._power_switch.set_active(bool(snapshot.powered))
        self._power_switch.handler_unblock_by_func(self._on_power_switch_changed)

        if not snapshot.available:
            self._status.set_text(snapshot.status_message or "Bluetooth no disponible")
        elif snapshot.error_message:
            self._status.set_text(snapshot.status_message or "Bluetooth")
        else:
            self._status.set_text(snapshot.status_message or "")

        self._error.set_text(snapshot.error_message or "")
        self._error.set_visible(bool(snapshot.error_message))

        self._scan_button.set_sensitive(snapshot.available and snapshot.powered)
        if snapshot.discovering:
            self._scan_button.set_label("Buscando…")
        else:
            self._scan_button.set_label("Buscar dispositivos")

        for child in self._device_list.get_children():
            self._device_list.remove(child)

        if not snapshot.available:
            empty = Gtk.Label(label="Instala bluez o conecta un adaptador Bluetooth.", xalign=0)
            empty.set_line_wrap(True)
            empty.get_style_context().add_class("control-center-detail-muted")
            self._device_list.add(empty)
            self._device_list.show_all()
            return

        if not snapshot.powered:
            empty = Gtk.Label(label="Activa Bluetooth para ver y conectar dispositivos.", xalign=0)
            empty.set_line_wrap(True)
            empty.get_style_context().add_class("control-center-detail-muted")
            self._device_list.add(empty)
            self._device_list.show_all()
            return

        if not snapshot.devices:
            empty = Gtk.Label(
                label="No hay dispositivos. Pulsa «Buscar dispositivos» y pon el accesorio en modo emparejamiento.",
                xalign=0,
            )
            empty.set_line_wrap(True)
            empty.get_style_context().add_class("control-center-detail-muted")
            self._device_list.add(empty)
            self._device_list.show_all()
            return

        for device in snapshot.devices:
            self._device_list.add(self._device_row(device))
        self._device_list.show_all()

    def _device_row(self, device: BluetoothDeviceSnapshot) -> Gtk.Widget:
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("control-center-wifi-row")
        if device.connected:
            row.get_style_context().add_class("control-center-wifi-row-active")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(4)
        box.set_margin_end(4)

        icon_name = "bluetooth-symbolic"
        if device.connected:
            icon_name = "bluetooth-active-symbolic"
        elif device.icon:
            # BlueZ icon names are often already symbolic-friendly enough.
            icon_name = device.icon if device.icon.endswith("-symbolic") else f"{device.icon}-symbolic"
        image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
        box.pack_start(image, False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        name = Gtk.Label(label=device_display_name(device), xalign=0)
        name.get_style_context().add_class("control-center-wifi-ssid")
        text.pack_start(name, False, False, 0)

        bits: list[str] = []
        if device.connecting:
            bits.append("Conectando…")
        elif device.connected:
            bits.append("Conectado")
        elif device.paired:
            bits.append("Emparejado")
        else:
            bits.append("Nuevo")
        if device.battery_percent is not None:
            bits.append(f"{device.battery_percent}%")
        detail = Gtk.Label(label=" · ".join(bits), xalign=0)
        detail.get_style_context().add_class("control-center-detail-muted")
        text.pack_start(detail, False, False, 0)
        box.pack_start(text, True, True, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        if device.connected:
            disconnect = Gtk.Button(label="Desconectar", relief=Gtk.ReliefStyle.NONE)
            disconnect.get_style_context().add_class("control-center-action")
            disconnect.set_sensitive(not device.connecting)
            disconnect.connect(
                "clicked",
                lambda *_args, path=device.path: self._on_disconnect(path),
            )
            actions.pack_start(disconnect, False, False, 0)
        else:
            connect = Gtk.Button(
                label="Conectar" if device.paired else "Emparejar",
                relief=Gtk.ReliefStyle.NONE,
            )
            connect.get_style_context().add_class("control-center-action")
            connect.set_sensitive(not device.connecting)
            connect.connect(
                "clicked",
                lambda *_args, path=device.path: self._on_connect(path),
            )
            actions.pack_start(connect, False, False, 0)

        if device.paired or device.connected:
            forget = Gtk.Button(label="Olvidar", relief=Gtk.ReliefStyle.NONE)
            forget.get_style_context().add_class("control-center-action")
            forget.set_sensitive(not device.connecting)
            forget.connect(
                "clicked",
                lambda *_args, path=device.path: self._on_forget(path),
            )
            actions.pack_start(forget, False, False, 0)

        box.pack_start(actions, False, False, 0)
        row.add(box)
        return row
