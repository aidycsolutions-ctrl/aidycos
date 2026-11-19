"""Control center popup shell with single-section and full layouts."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk

from ...config import (
    CONTROL_CENTER_POPUP_MAX_HEIGHT,
    CONTROL_CENTER_POPUP_OFFSET,
    CONTROL_CENTER_POPUP_WIDTH,
)
from ...popup_handle import pointer_inside_widget, present_popup, hide_popup
from ...popup_spawn import publish_popup_spawn
from ...servicios.bluetooth.service import BluetoothService
from ...servicios.red.network import NetworkService, wifi_scan_allowed
from ...ui.starfield import install_starfield, resolve_event_bus
from ...window_identity import (
    TITLE_CONTROL_CENTER,
    TITLE_NETWORK_PANEL,
    configure_interactive_popup,
    configure_toplevel,
    position_popup_below_anchor,
    register_shell_popup,
    schedule_popup_position,
)
from .bluetooth_section import ControlCenterBluetoothSection
from .network_section import ControlCenterNetworkSection
from .placeholder_section import ControlCenterPlaceholderSection
from .views import ControlCenterView

try:
    from ...window_identity import TITLE_PHONE_PANEL
except ImportError:  # pragma: no cover
    TITLE_PHONE_PANEL = "Teléfono"

try:
    from ...servicios.movil.kdeconnect import PhoneService
except Exception:  # pragma: no cover — older Jugoo without movil
    PhoneService = None  # type: ignore[misc, assignment]

try:
    from ...servicios.movil.remoto.servidor import RemoteControlService
except Exception:  # pragma: no cover
    RemoteControlService = None  # type: ignore[misc, assignment]

try:
    from .phone_section import ControlCenterPhoneSection
except Exception:  # pragma: no cover
    ControlCenterPhoneSection = None  # type: ignore[misc, assignment]

try:
    from .remote_section import ControlCenterRemoteSection
except Exception:  # pragma: no cover
    ControlCenterRemoteSection = None  # type: ignore[misc, assignment]

TITLE_BLUETOOTH_PANEL = "Bluetooth"
_PHONE_VIEW = getattr(ControlCenterView, "PHONE", None)
_BLUETOOTH_VIEW = getattr(ControlCenterView, "BLUETOOTH", None)

_VIEW_WINDOW_NAMES = {
    ControlCenterView.FULL: "shell-control-center",
    ControlCenterView.NETWORK: "shell-network-panel",
    ControlCenterView.AUDIO: "shell-audio-panel",
    ControlCenterView.MEDIA: "shell-media-panel",
}
_VIEW_TITLES = {
    ControlCenterView.FULL: TITLE_CONTROL_CENTER,
    ControlCenterView.NETWORK: TITLE_NETWORK_PANEL,
    ControlCenterView.AUDIO: TITLE_CONTROL_CENTER,
    ControlCenterView.MEDIA: TITLE_CONTROL_CENTER,
}
_VIEW_HEADINGS = {
    ControlCenterView.FULL: "Centro de control",
    ControlCenterView.NETWORK: "Red",
    ControlCenterView.AUDIO: "Audio",
    ControlCenterView.MEDIA: "Media",
}
if _BLUETOOTH_VIEW is not None:
    _VIEW_WINDOW_NAMES[_BLUETOOTH_VIEW] = "shell-bluetooth-panel"
    _VIEW_TITLES[_BLUETOOTH_VIEW] = TITLE_BLUETOOTH_PANEL
    _VIEW_HEADINGS[_BLUETOOTH_VIEW] = "Bluetooth"
if _PHONE_VIEW is not None:
    _VIEW_WINDOW_NAMES[_PHONE_VIEW] = "shell-phone-panel"
    _VIEW_TITLES[_PHONE_VIEW] = TITLE_PHONE_PANEL
    _VIEW_HEADINGS[_PHONE_VIEW] = "Teléfono"


class ControlCenterPopup(Gtk.Window):
    """Anchored popup that can show one section or the full control center."""

    def __init__(
        self,
        shell_window: Gtk.Window,
        network_service: NetworkService,
        *,
        view: ControlCenterView = ControlCenterView.FULL,
        phone_service=None,
        remote_service=None,
        bluetooth_service: BluetoothService | None = None,
    ) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)

        self._shell_window = shell_window
        self._service = network_service
        self._phone_service = phone_service
        self._remote_service = remote_service
        self._bluetooth_service = bluetooth_service
        self._remote_section = None
        self._view = view
        self._anchor_button: Gtk.Widget | None = None
        self._fixed_popup_top: int | None = None
        self._network_section: ControlCenterNetworkSection | None = None
        self._bluetooth_section: ControlCenterBluetoothSection | None = None
        self._phone_section = None

        self.set_name(_VIEW_WINDOW_NAMES.get(view, "shell-control-center"))
        register_shell_popup(self, shell_window)
        configure_toplevel(self, title=_VIEW_TITLES.get(view, TITLE_CONTROL_CENTER))
        configure_interactive_popup(self)
        self.set_default_size(CONTROL_CENTER_POPUP_WIDTH, -1)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.get_style_context().add_class("control-center-popup-content")
        install_starfield(
            self,
            outer,
            resolve_event_bus(shell_window),
            corner_radius=16.0,
        )

        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header.get_style_context().add_class("control-center-popup-header")
        title = Gtk.Label(label=_VIEW_HEADINGS.get(view, "Centro de control"), xalign=0)
        title.get_style_context().add_class("control-center-popup-title")
        header.pack_start(title, False, False, 0)
        outer.pack_start(header, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_max_content_height(CONTROL_CENTER_POPUP_MAX_HEIGHT)
        scrolled.get_style_context().add_class("control-center-popup-scroll")
        outer.pack_start(scrolled, False, False, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.get_style_context().add_class("control-center-popup-body")
        scrolled.add(body)

        if view in (ControlCenterView.FULL, ControlCenterView.NETWORK):
            self._network_section = ControlCenterNetworkSection(
                network_service,
                on_toggle_ethernet=network_service.toggle_ethernet,
                on_toggle_wireless=network_service.set_wireless_enabled,
                on_request_wifi_scan=network_service.request_wifi_scan,
                on_connect_wifi=network_service.connect_wifi,
                on_disconnect_wifi=network_service.disconnect_wifi,
                on_toggle_hotspot=lambda enabled, ssid, password, band: (
                    network_service.set_hotspot_enabled(
                        enabled,
                        ssid=ssid,
                        password=password,
                        band=band,
                    )
                ),
                on_apply_hotspot=network_service.apply_hotspot_config,
                on_forget_wifi=getattr(network_service, "forget_wifi", None),
                on_request_wifi_credentials=getattr(
                    network_service,
                    "request_active_wifi_credentials",
                    None,
                ),
            )
            body.pack_start(self._network_section, False, False, 0)

        bluetooth_views = {ControlCenterView.FULL, ControlCenterView.NETWORK}
        if _BLUETOOTH_VIEW is not None:
            bluetooth_views.add(_BLUETOOTH_VIEW)
        if bluetooth_service is not None and view in bluetooth_views:
            self._bluetooth_section = ControlCenterBluetoothSection(
                on_toggle_powered=bluetooth_service.set_powered,
                on_request_discovery=bluetooth_service.request_discovery,
                on_connect=bluetooth_service.connect_device,
                on_disconnect=bluetooth_service.disconnect_device,
                on_forget=bluetooth_service.forget_device,
            )
            body.pack_start(self._bluetooth_section, False, False, 0)

        phone_views = {ControlCenterView.FULL}
        if _PHONE_VIEW is not None:
            phone_views.add(_PHONE_VIEW)
        if (
            phone_service is not None
            and ControlCenterPhoneSection is not None
            and view in phone_views
        ):
            self._phone_section = ControlCenterPhoneSection(phone_service)
            body.pack_start(self._phone_section, False, False, 0)

        if (
            remote_service is not None
            and ControlCenterRemoteSection is not None
            and view in phone_views
        ):
            self._remote_section = ControlCenterRemoteSection(remote_service)
            body.pack_start(self._remote_section, False, False, 0)

        if view == ControlCenterView.FULL:
            body.pack_start(
                ControlCenterPlaceholderSection(
                    "Audio",
                    module_class="control-center-audio-section",
                ),
                False,
                False,
                0,
            )
            body.pack_start(
                ControlCenterPlaceholderSection(
                    "Media",
                    module_class="control-center-media-section",
                ),
                False,
                False,
                0,
            )
            body.pack_start(
                ControlCenterPlaceholderSection(
                    "Notificaciones",
                    module_class="control-center-notifications-section",
                ),
                False,
                False,
                0,
            )

    @property
    def view(self) -> ControlCenterView:
        return self._view

    def open_for(self, anchor_button: Gtk.Widget) -> None:
        self._anchor_button = anchor_button
        self._fixed_popup_top = None
        if self._remote_section is not None and self._remote_service is not None:
            refresh = getattr(self._remote_service, "refresh_address", None)
            if callable(refresh):
                refresh()
        self.refresh()
        if (
            self._network_section is not None
            and wifi_scan_allowed(self._service.snapshot)
        ):
            self._service.request_wifi_scan()
        if (
            self._bluetooth_section is not None
            and self._bluetooth_service is not None
            and self._bluetooth_service.snapshot.powered
        ):
            self._bluetooth_service.request_discovery()
        publish_popup_spawn(
            self,
            anchor_button,
            title=_VIEW_TITLES.get(self._view, TITLE_CONTROL_CENTER),
            offset=CONTROL_CENTER_POPUP_OFFSET,
        )
        present_popup(self)
        schedule_popup_position(self._position_after_show)

    def close_popup(self) -> None:
        self._anchor_button = None
        self._fixed_popup_top = None
        hide_popup(self)

    def pointer_is_inside(self) -> bool:
        return pointer_inside_widget(self)

    def refresh(self) -> None:
        if self._network_section is not None:
            self._network_section.refresh(self._service.snapshot)
        if self._bluetooth_section is not None and self._bluetooth_service is not None:
            self._bluetooth_section.refresh(self._bluetooth_service.snapshot)
        if self._phone_section is not None and self._phone_service is not None:
            self._phone_section.refresh(self._phone_service.snapshot)
        if self._remote_section is not None and self._remote_service is not None:
            self._remote_section.refresh(self._remote_service.snapshot)

    def _position_after_show(self) -> bool:
        if self._anchor_button is None:
            return False
        self._fixed_popup_top = position_popup_below_anchor(
            self,
            self._anchor_button,
            title=_VIEW_TITLES.get(self._view, TITLE_CONTROL_CENTER),
            offset=CONTROL_CENTER_POPUP_OFFSET,
            fixed_top=self._fixed_popup_top,
        )
        return False
