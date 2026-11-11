"""Network section for the control center (Ethernet + Wi-Fi)."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, GLib, Gtk

from .hotspot_section import ControlCenterHotspotSection
from ...models import NetworkSnapshot, WifiAccessPointSnapshot, WifiCredentials
from ...servicios.red.network import (
    NetworkService,
    build_ethernet_tooltip,
    ethernet_icon_name,
    format_link_speed,
    wifi_qr_payload,
)
from ...ui import ShellModule

try:
    import qrcode
except ImportError:
    qrcode = None

_QR_SIZE_PX = 180
_PASSWORD_MASK = "••••••••"


def wifi_qr_matrix(payload: str) -> list[list[bool]] | None:
    if qrcode is None:
        return None
    code = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(payload)
    code.make(fit=True)
    return code.get_matrix()


class ControlCenterNetworkSection(ShellModule):
    """Ethernet and Wi-Fi controls backed by NetworkService."""

    def __init__(
        self,
        network_service: NetworkService,
        *,
        on_toggle_ethernet: Callable[[], None],
        on_toggle_wireless: Callable[[bool], None],
        on_request_wifi_scan: Callable[[], None],
        on_connect_wifi: Callable[[str, str, str], None],
        on_disconnect_wifi: Callable[[], None],
        on_toggle_hotspot: Callable[[bool, str, str, str], None],
        on_apply_hotspot: Callable[[str, str, str], None],
        on_forget_wifi: Callable[[str], None] | None = None,
        on_request_wifi_credentials: (
            Callable[[Callable[[WifiCredentials | None, str], None]], None] | None
        ) = None,
    ) -> None:
        super().__init__("control-center-network-section", spacing=0)
        self._service = network_service
        self._on_toggle_ethernet = on_toggle_ethernet
        self._on_toggle_wireless = on_toggle_wireless
        self._on_request_wifi_scan = on_request_wifi_scan
        self._on_connect_wifi = on_connect_wifi
        self._on_disconnect_wifi = on_disconnect_wifi
        self._on_forget_wifi = on_forget_wifi
        self._on_request_wifi_credentials = on_request_wifi_credentials
        self._pending_ap_path: str | None = None
        self._pending_ssid = ""
        self._prompted_error = ""
        self._shared_credentials: WifiCredentials | None = None
        self._qr_matrix: list[list[bool]] | None = None

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.get_style_context().add_class("control-center-section")
        self.pack_start(outer, True, True, 0)

        title = Gtk.Label(xalign=0)
        title.get_style_context().add_class("control-center-section-title")
        title.set_markup("<b>Red</b>")
        outer.pack_start(title, False, False, 0)

        outer.pack_start(self._build_ethernet_block(), False, False, 0)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        outer.pack_start(self._build_wifi_block(), False, False, 0)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        self._hotspot_section = ControlCenterHotspotSection(
            on_toggle_hotspot=on_toggle_hotspot,
            on_apply_hotspot=on_apply_hotspot,
        )
        outer.pack_start(self._hotspot_section, False, False, 0)

    def refresh(self, snapshot: NetworkSnapshot) -> None:
        self._sync_ethernet(snapshot)
        self._sync_wifi(snapshot)
        self._hotspot_section.refresh(snapshot)

    def _build_ethernet_block(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.get_style_context().add_class("control-center-subsection")

        heading_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._ethernet_icon = Gtk.Image.new_from_icon_name(
            "network-wired-disconnected-symbolic",
            Gtk.IconSize.MENU,
        )
        self._ethernet_icon.get_style_context().add_class("control-center-ethernet-icon")
        heading_row.pack_start(self._ethernet_icon, False, False, 0)
        heading = Gtk.Label(label="Ethernet", xalign=0)
        heading.get_style_context().add_class("control-center-subsection-title")
        heading_row.pack_start(heading, True, True, 0)
        box.pack_start(heading_row, False, False, 0)

        self._ethernet_status = Gtk.Label(xalign=0)
        self._ethernet_status.get_style_context().add_class("control-center-detail")
        box.pack_start(self._ethernet_status, False, False, 0)

        self._ethernet_details = Gtk.Label(xalign=0)
        self._ethernet_details.get_style_context().add_class("control-center-detail-muted")
        self._ethernet_details.set_line_wrap(True)
        box.pack_start(self._ethernet_details, False, False, 0)

        self._ethernet_button = Gtk.Button(label="Alternar conexión", relief=Gtk.ReliefStyle.NONE)
        self._ethernet_button.get_style_context().add_class("control-center-action")
        self._ethernet_button.connect("clicked", lambda *_args: self._on_toggle_ethernet())
        box.pack_start(self._ethernet_button, False, False, 0)
        return box

    def _build_wifi_block(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.get_style_context().add_class("control-center-subsection")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        heading = Gtk.Label(label="Wi-Fi", xalign=0)
        heading.get_style_context().add_class("control-center-subsection-title")
        heading.set_hexpand(True)
        header.pack_start(heading, True, True, 0)

        self._wifi_switch = Gtk.Switch()
        self._wifi_switch.set_halign(Gtk.Align.END)
        self._wifi_switch.connect("notify::active", self._on_wifi_switch_changed)
        header.pack_start(self._wifi_switch, False, False, 0)
        box.pack_start(header, False, False, 0)

        self._wifi_status = Gtk.Label(xalign=0)
        self._wifi_status.get_style_context().add_class("control-center-detail")
        box.pack_start(self._wifi_status, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions.set_halign(Gtk.Align.END)
        self._wifi_share_button = Gtk.Button(label="Compartir", relief=Gtk.ReliefStyle.NONE)
        self._wifi_share_button.get_style_context().add_class("control-center-action")
        self._wifi_share_button.set_tooltip_text("Ver contraseña y código QR de la red actual")
        self._wifi_share_button.connect("clicked", self._on_wifi_share_clicked)
        actions.pack_start(self._wifi_share_button, False, False, 0)
        self._wifi_disconnect_button = Gtk.Button(label="Desconectar", relief=Gtk.ReliefStyle.NONE)
        self._wifi_disconnect_button.get_style_context().add_class("control-center-action")
        self._wifi_disconnect_button.connect("clicked", lambda *_args: self._on_disconnect_wifi())
        actions.pack_start(self._wifi_disconnect_button, False, False, 0)

        scan_button = Gtk.Button(label="Buscar redes", relief=Gtk.ReliefStyle.NONE)
        scan_button.get_style_context().add_class("control-center-action")
        scan_button.connect("clicked", lambda *_args: self._on_request_wifi_scan())
        actions.pack_start(scan_button, False, False, 0)
        box.pack_start(actions, False, False, 0)

        box.pack_start(self._build_share_panel(), False, False, 0)

        self._wifi_list = Gtk.ListBox()
        self._wifi_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._wifi_list.get_style_context().add_class("control-center-wifi-list")
        box.pack_start(self._wifi_list, False, False, 0)

        password_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._wifi_password_entry = Gtk.Entry()
        self._wifi_password_entry.set_visibility(False)
        self._wifi_password_entry.set_placeholder_text("Contraseña Wi-Fi")
        self._wifi_password_entry.set_hexpand(True)
        password_row.pack_start(self._wifi_password_entry, True, True, 0)
        self._wifi_password_entry.connect("activate", self._on_wifi_password_connect)
        self._wifi_password_reveal = Gtk.ToggleButton(label="Mostrar")
        self._wifi_password_reveal.set_relief(Gtk.ReliefStyle.NONE)
        self._wifi_password_reveal.connect("toggled", self._on_password_reveal)
        password_row.pack_start(self._wifi_password_reveal, False, False, 0)
        self._wifi_password_button = Gtk.Button(label="Conectar", relief=Gtk.ReliefStyle.NONE)
        self._wifi_password_button.get_style_context().add_class("control-center-action")
        self._wifi_password_button.connect("clicked", self._on_wifi_password_connect)
        password_row.pack_start(self._wifi_password_button, False, False, 0)
        self._wifi_password_row = password_row
        box.pack_start(self._wifi_password_row, False, False, 0)
        _hide_until_requested(self._wifi_password_row)
        return box

    def _build_share_panel(self) -> Gtk.Widget:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.get_style_context().add_class("control-center-wifi-share")

        self._share_ssid = Gtk.Label(xalign=0)
        self._share_ssid.get_style_context().add_class("control-center-detail")
        self._share_ssid.set_selectable(True)
        panel.pack_start(self._share_ssid, False, False, 0)

        password_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._share_password = Gtk.Label(xalign=0)
        self._share_password.get_style_context().add_class("control-center-detail")
        self._share_password.set_selectable(True)
        self._share_password.set_hexpand(True)
        password_row.pack_start(self._share_password, True, True, 0)
        self._share_reveal = Gtk.ToggleButton(label="Mostrar")
        self._share_reveal.set_relief(Gtk.ReliefStyle.NONE)
        self._share_reveal.connect("toggled", lambda *_args: self._sync_share_password())
        password_row.pack_start(self._share_reveal, False, False, 0)
        self._share_copy = Gtk.Button(label="Copiar", relief=Gtk.ReliefStyle.NONE)
        self._share_copy.get_style_context().add_class("control-center-action")
        self._share_copy.connect("clicked", self._on_share_copy)
        password_row.pack_start(self._share_copy, False, False, 0)
        panel.pack_start(password_row, False, False, 0)

        self._share_qr = Gtk.DrawingArea()
        self._share_qr.set_size_request(_QR_SIZE_PX, _QR_SIZE_PX)
        self._share_qr.set_halign(Gtk.Align.CENTER)
        self._share_qr.connect("draw", self._on_draw_qr)
        panel.pack_start(self._share_qr, False, False, 0)

        self._share_hint = Gtk.Label(xalign=0)
        self._share_hint.get_style_context().add_class("control-center-detail-muted")
        self._share_hint.set_line_wrap(True)
        panel.pack_start(self._share_hint, False, False, 0)

        close_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        close_row.set_halign(Gtk.Align.END)
        close_button = Gtk.Button(label="Cerrar", relief=Gtk.ReliefStyle.NONE)
        close_button.get_style_context().add_class("control-center-action")
        close_button.connect("clicked", lambda *_args: self._close_share_panel())
        close_row.pack_start(close_button, False, False, 0)
        panel.pack_start(close_row, False, False, 0)

        self._share_panel = panel
        _hide_until_requested(panel)
        return panel

    def _sync_ethernet(self, snapshot: NetworkSnapshot) -> None:
        ethernet = snapshot.ethernet
        if ethernet is None:
            self._ethernet_icon.set_from_icon_name(
                "network-wired-disconnected-symbolic",
                Gtk.IconSize.MENU,
            )
            self._ethernet_status.set_text("No hay interfaz Ethernet disponible")
            self._ethernet_details.set_text("")
            self._ethernet_button.set_sensitive(False)
            return

        icon_name = ethernet_icon_name(snapshot)
        if icon_name is not None:
            self._ethernet_icon.set_from_icon_name(icon_name, Gtk.IconSize.MENU)
        self._ethernet_button.set_sensitive(True)
        if ethernet.state == "connected":
            internet = snapshot.connectivity.summary_label
            self._ethernet_status.set_text(f"Conectado · {internet}")
        else:
            labels = {
                "disconnected": "Desconectado",
                "connecting": "Conectando…",
                "disconnecting": "Desconectando…",
                "unavailable": "No disponible",
                "failed": "Error",
            }
            self._ethernet_status.set_text(labels.get(ethernet.state, ethernet.state))

        details: list[str] = []
        if ethernet.interface:
            details.append(f"Interfaz: {ethernet.interface}")
        if ethernet.ip_address:
            details.append(f"IP: {ethernet.ip_address}")
        speed = format_link_speed(ethernet.speed_mbps)
        if speed:
            details.append(f"Velocidad: {speed}")
        if ethernet.connection_name:
            details.append(f"Perfil: {ethernet.connection_name}")
        self._ethernet_details.set_text("\n".join(details))
        self._ethernet_button.set_tooltip_text(build_ethernet_tooltip(snapshot))

    def _sync_wifi(self, snapshot: NetworkSnapshot) -> None:
        self._wifi_switch.handler_block_by_func(self._on_wifi_switch_changed)
        self._wifi_switch.set_sensitive(snapshot.wireless_hardware_enabled)
        self._wifi_switch.set_active(snapshot.wireless_enabled)
        self._wifi_switch.handler_unblock_by_func(self._on_wifi_switch_changed)

        wifi = snapshot.wifi
        if not snapshot.wireless_hardware_enabled:
            self._wifi_status.set_text("Wi-Fi no disponible en este equipo")
        elif not snapshot.wireless_enabled:
            self._wifi_status.set_text("Wi-Fi desactivado")
        elif wifi is None:
            self._wifi_status.set_text("Sin adaptador Wi-Fi gestionado")
        elif snapshot.wifi_connection_error:
            self._wifi_status.set_text(snapshot.wifi_connection_error)
        elif snapshot.wifi_connection_target and wifi.state in {"connecting", "failed"}:
            self._wifi_status.set_text(f"Conectando a {snapshot.wifi_connection_target}…")
        elif wifi.state == "connected":
            ssid = wifi.connection_name or wifi.interface
            self._wifi_status.set_text(f"Conectado a {ssid}")
        else:
            labels = {
                "disconnected": "Desconectado",
                "connecting": "Conectando…",
                "unavailable": "No disponible",
            }
            self._wifi_status.set_text(labels.get(wifi.state, wifi.state))

        wifi_connected = wifi is not None and wifi.connected and not snapshot.hotspot.active
        self._wifi_disconnect_button.set_sensitive(wifi_connected)
        self._wifi_share_button.set_sensitive(
            wifi_connected and self._on_request_wifi_credentials is not None,
        )
        if not wifi_connected:
            self._close_share_panel()

        for child in self._wifi_list.get_children():
            self._wifi_list.remove(child)

        if not snapshot.wireless_enabled:
            self._wifi_password_row.hide()
            return

        self._maybe_prompt_password_after_error(snapshot)

        if not snapshot.wifi_access_points:
            wifi = snapshot.wifi
            if snapshot.wifi_connection_error.startswith(
                ("Activando Wi-Fi", "Wi-Fi aún no está listo", "Buscando redes"),
            ):
                empty_text = snapshot.wifi_connection_error
            elif wifi is not None and wifi.state in {"unavailable", "unmanaged", "unknown"}:
                empty_text = (
                    "Wi-Fi no gestionado o no listo para buscar. "
                    "Espera unos segundos y pulsa «Buscar redes»."
                )
            elif wifi is None:
                empty_text = "Sin adaptador Wi-Fi gestionado por NetworkManager."
            else:
                empty_text = "No se encontraron redes. Pulsa «Buscar redes»."
            empty = Gtk.Label(label=empty_text, xalign=0)
            empty.set_line_wrap(True)
            empty.get_style_context().add_class("control-center-detail-muted")
            self._wifi_list.add(empty)
            self._wifi_list.show_all()
            return

        for access_point in snapshot.wifi_access_points:
            self._wifi_list.add(self._wifi_row(access_point))
            if access_point.active and access_point.ssid == self._pending_ssid:
                self._pending_ap_path = None
                self._pending_ssid = ""
                self._wifi_password_row.hide()
        self._wifi_list.show_all()

    def _wifi_row(self, access_point: WifiAccessPointSnapshot) -> Gtk.Widget:
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("control-center-wifi-row")
        if access_point.active:
            row.get_style_context().add_class("control-center-wifi-row-active")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        row.add(box)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        text_box.set_hexpand(True)
        title = Gtk.Label(xalign=0)
        title.get_style_context().add_class("control-center-wifi-ssid")
        title.set_markup(f"<b>{GLib.markup_escape_text(access_point.ssid)}</b>")
        text_box.pack_start(title, False, False, 0)

        meta_parts = [f"{access_point.strength}%"]
        if access_point.frequency_mhz:
            meta_parts.append(f"{access_point.frequency_mhz} MHz")
        if access_point.secured:
            meta_parts.append("Protegida")
        if access_point.saved:
            meta_parts.append("Guardada")
        meta = Gtk.Label(label=" · ".join(meta_parts), xalign=0)
        meta.get_style_context().add_class("control-center-detail-muted")
        text_box.pack_start(meta, False, False, 0)
        box.pack_start(text_box, True, True, 0)

        if access_point.saved and self._on_forget_wifi is not None:
            forget = Gtk.Button(label="Olvidar", relief=Gtk.ReliefStyle.NONE)
            forget.get_style_context().add_class("control-center-action")
            forget.set_tooltip_text("Borrar la contraseña guardada de esta red")
            forget.connect(
                "clicked",
                lambda _btn, ssid=access_point.ssid: self._on_forget_wifi(ssid),
            )
            box.pack_start(forget, False, False, 0)

        button = Gtk.Button(
            label="Conectado" if access_point.active else "Conectar",
            relief=Gtk.ReliefStyle.NONE,
        )
        button.set_sensitive(not access_point.active)
        button.get_style_context().add_class("control-center-action")
        button.connect(
            "clicked",
            lambda _btn, ap=access_point: self._on_wifi_row_connect(ap),
        )
        box.pack_start(button, False, False, 0)
        return row

    def _on_wifi_switch_changed(self, switch: Gtk.Switch, _pspec) -> None:
        self._on_toggle_wireless(switch.get_active())

    def _on_wifi_row_connect(self, access_point: WifiAccessPointSnapshot) -> None:
        self._wifi_status.set_text(f"Preparando conexión a {access_point.ssid}…")
        if access_point.secured and not access_point.saved:
            self._show_password_prompt(access_point)
            return
        self._pending_ap_path = None
        self._wifi_password_row.hide()
        self._on_connect_wifi(access_point.path, "", access_point.ssid)

    def _show_password_prompt(self, access_point: WifiAccessPointSnapshot) -> None:
        self._pending_ap_path = access_point.path
        self._pending_ssid = access_point.ssid
        self._wifi_password_entry.set_text("")
        self._wifi_password_entry.set_placeholder_text(
            f"Contraseña de {access_point.ssid}",
        )
        self._wifi_password_row.show()
        self._wifi_password_entry.grab_focus()

    def _maybe_prompt_password_after_error(self, snapshot: NetworkSnapshot) -> None:
        """A saved profile with a wrong/stale key fails: ask for the key once per error."""
        error = snapshot.wifi_connection_error
        if not error:
            self._prompted_error = ""
            return
        if error == self._prompted_error:
            return
        target = snapshot.wifi_connection_target
        for access_point in snapshot.wifi_access_points:
            if access_point.ssid == target and access_point.secured:
                self._prompted_error = error
                self._show_password_prompt(access_point)
                return

    def _on_wifi_share_clicked(self, *_args) -> None:
        if self._on_request_wifi_credentials is None:
            return
        self._shared_credentials = None
        self._qr_matrix = None
        self._share_reveal.set_active(False)
        self._share_ssid.set_text("Leyendo datos de la red…")
        self._share_password.set_text("")
        self._share_hint.set_text("")
        self._share_copy.set_sensitive(False)
        self._share_qr.hide()
        self._share_panel.show()
        self._on_request_wifi_credentials(self._on_wifi_credentials_ready)

    def _on_wifi_credentials_ready(
        self,
        credentials: WifiCredentials | None,
        error: str,
    ) -> None:
        if not self._share_panel.get_visible():
            return
        if credentials is None:
            self._share_ssid.set_text(error or "No se pudo leer la red")
            return
        self._shared_credentials = credentials
        self._share_ssid.set_markup(
            f"Red: <b>{GLib.markup_escape_text(credentials.ssid)}</b>",
        )
        self._share_copy.set_sensitive(bool(credentials.password))
        self._sync_share_password()
        self._qr_matrix = wifi_qr_matrix(wifi_qr_payload(credentials))
        if self._qr_matrix is None:
            self._share_hint.set_text("Instala python-qrcode para ver el código QR.")
        else:
            self._share_hint.set_text("Escanea con la cámara del teléfono para conectarte.")
            self._share_qr.show()
            self._share_qr.queue_draw()

    def _sync_share_password(self) -> None:
        credentials = self._shared_credentials
        visible = self._share_reveal.get_active()
        self._share_reveal.set_label("Ocultar" if visible else "Mostrar")
        if credentials is None:
            return
        if not credentials.password:
            self._share_password.set_text("Red abierta (sin contraseña)")
            self._share_reveal.set_sensitive(False)
            return
        self._share_reveal.set_sensitive(True)
        shown = credentials.password if visible else _PASSWORD_MASK
        self._share_password.set_text(f"Contraseña: {shown}")

    def _on_share_copy(self, *_args) -> None:
        credentials = self._shared_credentials
        if credentials is None or not credentials.password:
            return
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(credentials.password, -1)
        clipboard.store()
        self._share_hint.set_text("Contraseña copiada al portapapeles.")

    def _close_share_panel(self) -> None:
        self._shared_credentials = None
        self._qr_matrix = None
        self._share_password.set_text("")
        self._share_panel.hide()

    def _on_draw_qr(self, area: Gtk.DrawingArea, cr) -> bool:
        matrix = self._qr_matrix
        if not matrix:
            return False
        size = min(area.get_allocated_width(), area.get_allocated_height())
        modules = len(matrix)
        cell = size / modules
        offset_x = (area.get_allocated_width() - size) / 2
        offset_y = (area.get_allocated_height() - size) / 2
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(offset_x, offset_y, size, size)
        cr.fill()
        cr.set_source_rgb(0, 0, 0)
        for row_index, row in enumerate(matrix):
            for col_index, dark in enumerate(row):
                if dark:
                    cr.rectangle(
                        offset_x + col_index * cell,
                        offset_y + row_index * cell,
                        cell + 0.5,
                        cell + 0.5,
                    )
        cr.fill()
        return False

    def _on_wifi_password_connect(self, *_args) -> None:
        if self._pending_ap_path is None:
            return
        password = self._wifi_password_entry.get_text()
        if not password:
            self._wifi_status.set_text("Escribe la contraseña de la red Wi-Fi")
            self._wifi_password_entry.grab_focus()
            return
        self._wifi_status.set_text("Conectando…")
        self._on_connect_wifi(
            self._pending_ap_path,
            password,
            self._pending_ssid,
        )

    def _on_password_reveal(self, button: Gtk.ToggleButton) -> None:
        visible = button.get_active()
        self._wifi_password_entry.set_visibility(visible)
        button.set_label("Ocultar" if visible else "Mostrar")


def _hide_until_requested(widget: Gtk.Widget) -> None:
    """Keep the popup's window.show_all() from revealing on-demand rows."""
    widget.show_all()
    widget.hide()
    widget.set_no_show_all(True)
