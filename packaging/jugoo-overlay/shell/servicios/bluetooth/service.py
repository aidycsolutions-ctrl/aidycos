"""BlueZ-backed Bluetooth monitoring and control for Jugoo."""

from __future__ import annotations

import logging
import subprocess
from typing import Any

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gio, GLib

from ...eventbus import EventBus
from ...models import BluetoothDeviceSnapshot, BluetoothSnapshot

BLUETOOTH_CHANGED = "bluetooth_changed"
BLUETOOTH_CLICKED = "bluetooth_clicked"

BLUEZ_BUS = "org.bluez"
BLUEZ_ROOT = "/org/bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
BATTERY_IFACE = "org.bluez.Battery1"
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
DBUS_PROPERTIES = "org.freedesktop.DBus.Properties"

_DBUS_TIMEOUT_MS = 8_000
_POLL_MS = 4_000
_DISCOVERY_AUTO_STOP_MS = 20_000

_logger = logging.getLogger(__name__)


def bluetooth_bar_icon_name(snapshot: BluetoothSnapshot) -> str:
    if not snapshot.available:
        return "bluetooth-disabled-symbolic"
    if not snapshot.powered:
        return "bluetooth-disabled-symbolic"
    if any(device.connected for device in snapshot.devices):
        return "bluetooth-active-symbolic"
    return "bluetooth-symbolic"


def bluetooth_bar_tooltip(snapshot: BluetoothSnapshot) -> str:
    if not snapshot.available:
        return snapshot.status_message or "Bluetooth no disponible"
    if not snapshot.powered:
        return "Bluetooth desactivado"
    connected = [d for d in snapshot.devices if d.connected]
    if connected:
        names = ", ".join(d.alias or d.name or d.address for d in connected[:3])
        return f"Bluetooth conectado · {names}"
    if snapshot.discovering:
        return "Buscando dispositivos Bluetooth…"
    return "Bluetooth activado"


def device_display_name(device: BluetoothDeviceSnapshot) -> str:
    return (device.alias or device.name or device.address).strip() or device.address


def _variant_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    try:
        return bool(value.unpack())
    except Exception:
        try:
            return bool(value)
        except Exception:
            return default


def _variant_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        text = value.unpack()
    except Exception:
        text = value
    return str(text or default)


def _variant_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value.unpack())
    except Exception:
        try:
            return int(value)
        except Exception:
            return None


class BluetoothService:
    """Owns Bluetooth snapshots and publishes ``bluetooth_changed``."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._snapshot = BluetoothSnapshot.unavailable("Iniciando Bluetooth…")
        self._started = False
        self._emitted_once = False
        self._timer_id = 0
        self._discovery_stop_id = 0
        self._manager: Gio.DBusProxy | None = None
        self._adapter_path: str | None = None
        self._adapter: Gio.DBusProxy | None = None
        self._signal_ids: list[tuple[Gio.DBusProxy, int]] = []
        self._busy_paths: set[str] = set()
        self._last_error = ""

    @property
    def snapshot(self) -> BluetoothSnapshot:
        return self._snapshot

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._try_bind()
        self.refresh()
        self._timer_id = GLib.timeout_add(_POLL_MS, self._on_poll)

    def close(self) -> None:
        self._started = False
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0
        if self._discovery_stop_id:
            GLib.source_remove(self._discovery_stop_id)
            self._discovery_stop_id = 0
        for proxy, signal_id in self._signal_ids:
            try:
                proxy.disconnect(signal_id)
            except Exception:
                pass
        self._signal_ids.clear()
        self._manager = None
        self._adapter = None
        self._adapter_path = None

    def refresh(self) -> BluetoothSnapshot:
        try:
            snapshot = self._read_snapshot()
        except Exception as error:  # noqa: BLE001 — never crash the bar
            _logger.debug("bluetooth refresh failed: %s", error)
            snapshot = BluetoothSnapshot.unavailable("No se pudo leer BlueZ")
        if self._last_error and snapshot.available:
            snapshot = BluetoothSnapshot(
                available=snapshot.available,
                powered=snapshot.powered,
                discovering=snapshot.discovering,
                adapter_name=snapshot.adapter_name,
                adapter_address=snapshot.adapter_address,
                devices=snapshot.devices,
                status_message=snapshot.status_message,
                error_message=self._last_error,
            )
        self._publish(snapshot)
        return snapshot

    def set_powered(self, enabled: bool) -> None:
        def apply() -> None:
            self._last_error = ""
            if enabled:
                self._unblock_rfkill()
            if not self._ensure_adapter():
                self._last_error = "No hay adaptador Bluetooth"
                self.refresh()
                return
            try:
                assert self._adapter is not None
                self._adapter.call_sync(
                    "org.freedesktop.DBus.Properties.Set",
                    GLib.Variant(
                        "(ssv)",
                        (ADAPTER_IFACE, "Powered", GLib.Variant("b", bool(enabled))),
                    ),
                    Gio.DBusCallFlags.NONE,
                    _DBUS_TIMEOUT_MS,
                    None,
                )
                if enabled:
                    # Make pairing possible without a separate discoverable toggle.
                    self._set_adapter_prop("Pairable", True)
                else:
                    self.stop_discovery()
            except Exception as error:  # noqa: BLE001
                self._last_error = _friendly_bluez_error(error)
            self.refresh()

        GLib.idle_add(lambda: (apply(), False)[1])

    def request_discovery(self) -> None:
        def apply() -> None:
            self._last_error = ""
            if not self._ensure_adapter():
                self._last_error = "No hay adaptador Bluetooth"
                self.refresh()
                return
            try:
                assert self._adapter is not None
                powered = _variant_bool(self._adapter.get_cached_property("Powered"), False)
                if not powered:
                    self.set_powered(True)
                self._set_adapter_prop("Pairable", True)
                self._adapter.call_sync(
                    "StartDiscovery",
                    None,
                    Gio.DBusCallFlags.NONE,
                    _DBUS_TIMEOUT_MS,
                    None,
                )
                if self._discovery_stop_id:
                    GLib.source_remove(self._discovery_stop_id)
                self._discovery_stop_id = GLib.timeout_add(
                    _DISCOVERY_AUTO_STOP_MS,
                    self._auto_stop_discovery,
                )
            except Exception as error:  # noqa: BLE001
                message = str(error)
                if "InProgress" not in message:
                    self._last_error = _friendly_bluez_error(error)
            self.refresh()

        GLib.idle_add(lambda: (apply(), False)[1])

    def stop_discovery(self) -> None:
        if self._adapter is None:
            return
        try:
            self._adapter.call_sync(
                "StopDiscovery",
                None,
                Gio.DBusCallFlags.NONE,
                _DBUS_TIMEOUT_MS,
                None,
            )
        except Exception:
            pass
        if self._discovery_stop_id:
            GLib.source_remove(self._discovery_stop_id)
            self._discovery_stop_id = 0

    def connect_device(self, path: str) -> None:
        self._run_device_op(path, self._connect_device_body)

    def disconnect_device(self, path: str) -> None:
        self._run_device_op(path, self._disconnect_device_body)

    def forget_device(self, path: str) -> None:
        self._run_device_op(path, self._forget_device_body)

    def trust_device(self, path: str, trusted: bool = True) -> None:
        def body(device: Gio.DBusProxy) -> None:
            device.call_sync(
                "org.freedesktop.DBus.Properties.Set",
                GLib.Variant(
                    "(ssv)",
                    (DEVICE_IFACE, "Trusted", GLib.Variant("b", bool(trusted))),
                ),
                Gio.DBusCallFlags.NONE,
                _DBUS_TIMEOUT_MS,
                None,
            )

        self._run_device_op(path, body)

    def _connect_device_body(self, device: Gio.DBusProxy) -> None:
        paired = _variant_bool(device.get_cached_property("Paired"), False)
        if not paired:
            device.call_sync(
                "Pair",
                None,
                Gio.DBusCallFlags.NONE,
                max(_DBUS_TIMEOUT_MS, 30_000),
                None,
            )
        # Trust paired devices so they reconnect later.
        try:
            device.call_sync(
                "org.freedesktop.DBus.Properties.Set",
                GLib.Variant(
                    "(ssv)",
                    (DEVICE_IFACE, "Trusted", GLib.Variant("b", True)),
                ),
                Gio.DBusCallFlags.NONE,
                _DBUS_TIMEOUT_MS,
                None,
            )
        except Exception:
            pass
        device.call_sync(
            "Connect",
            None,
            Gio.DBusCallFlags.NONE,
            max(_DBUS_TIMEOUT_MS, 20_000),
            None,
        )

    def _disconnect_device_body(self, device: Gio.DBusProxy) -> None:
        device.call_sync(
            "Disconnect",
            None,
            Gio.DBusCallFlags.NONE,
            _DBUS_TIMEOUT_MS,
            None,
        )

    def _forget_device_body(self, device: Gio.DBusProxy) -> None:
        if self._adapter is None:
            raise RuntimeError("Sin adaptador")
        path = device.get_object_path()
        try:
            device.call_sync(
                "Disconnect",
                None,
                Gio.DBusCallFlags.NONE,
                _DBUS_TIMEOUT_MS,
                None,
            )
        except Exception:
            pass
        self._adapter.call_sync(
            "RemoveDevice",
            GLib.Variant("(o)", (path,)),
            Gio.DBusCallFlags.NONE,
            _DBUS_TIMEOUT_MS,
            None,
        )

    def _run_device_op(self, path: str, body) -> None:
        def apply() -> None:
            self._last_error = ""
            self._busy_paths.add(path)
            self.refresh()
            try:
                device = Gio.DBusProxy.new_for_bus_sync(
                    Gio.BusType.SYSTEM,
                    Gio.DBusProxyFlags.NONE,
                    None,
                    BLUEZ_BUS,
                    path,
                    DEVICE_IFACE,
                    None,
                )
                body(device)
            except Exception as error:  # noqa: BLE001
                self._last_error = _friendly_bluez_error(error)
            finally:
                self._busy_paths.discard(path)
                self.refresh()

        GLib.idle_add(lambda: (apply(), False)[1])

    def _auto_stop_discovery(self) -> bool:
        self._discovery_stop_id = 0
        self.stop_discovery()
        self.refresh()
        return False

    def _on_poll(self) -> bool:
        if not self._started:
            return False
        if self._manager is None or self._adapter is None:
            self._try_bind()
        self.refresh()
        return True

    def _try_bind(self) -> None:
        try:
            manager = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM,
                Gio.DBusProxyFlags.NONE,
                None,
                BLUEZ_BUS,
                "/",
                OBJECT_MANAGER,
                None,
            )
        except Exception as error:  # noqa: BLE001
            _logger.debug("BlueZ ObjectManager unavailable: %s", error)
            self._manager = None
            return
        self._manager = manager
        self._connect_signal(manager, "g-signal", self._on_manager_signal)
        self._ensure_adapter()

    def _ensure_adapter(self) -> bool:
        if self._adapter is not None and self._adapter_path:
            return True
        if self._manager is None:
            self._try_bind()
        if self._manager is None:
            return False
        try:
            managed = self._manager.call_sync(
                "GetManagedObjects",
                None,
                Gio.DBusCallFlags.NONE,
                _DBUS_TIMEOUT_MS,
                None,
            )
        except Exception as error:  # noqa: BLE001
            _logger.debug("GetManagedObjects failed: %s", error)
            return False
        objects = managed.unpack()[0] if managed is not None else {}
        for path, ifaces in objects.items():
            if ADAPTER_IFACE not in ifaces:
                continue
            try:
                adapter = Gio.DBusProxy.new_for_bus_sync(
                    Gio.BusType.SYSTEM,
                    Gio.DBusProxyFlags.NONE,
                    None,
                    BLUEZ_BUS,
                    path,
                    ADAPTER_IFACE,
                    None,
                )
            except Exception:
                continue
            self._adapter_path = path
            self._adapter = adapter
            self._connect_signal(adapter, "g-properties-changed", self._on_props_changed)
            return True
        return False

    def _connect_signal(self, proxy: Gio.DBusProxy, signal: str, handler) -> None:
        try:
            signal_id = proxy.connect(signal, handler)
            self._signal_ids.append((proxy, signal_id))
        except Exception as error:  # noqa: BLE001
            _logger.debug("signal connect failed: %s", error)

    def _on_manager_signal(self, _proxy, sender_name, signal_name, _parameters) -> None:
        if signal_name in {"InterfacesAdded", "InterfacesRemoved"}:
            GLib.idle_add(self._refresh_idle)

    def _on_props_changed(self, _proxy, _changed, _invalidated) -> None:
        GLib.idle_add(self._refresh_idle)

    def _refresh_idle(self) -> bool:
        self.refresh()
        return False

    def _set_adapter_prop(self, name: str, value: bool) -> None:
        if self._adapter is None:
            return
        try:
            self._adapter.call_sync(
                "org.freedesktop.DBus.Properties.Set",
                GLib.Variant(
                    "(ssv)",
                    (ADAPTER_IFACE, name, GLib.Variant("b", bool(value))),
                ),
                Gio.DBusCallFlags.NONE,
                _DBUS_TIMEOUT_MS,
                None,
            )
        except Exception:
            pass

    def _unblock_rfkill(self) -> None:
        try:
            subprocess.run(
                ["rfkill", "unblock", "bluetooth"],
                check=False,
                capture_output=True,
                timeout=3,
            )
        except Exception:
            pass

    def _read_snapshot(self) -> BluetoothSnapshot:
        if not self._ensure_adapter():
            return BluetoothSnapshot.unavailable(
                "Bluetooth no disponible (¿bluez / adaptador?)",
            )
        assert self._adapter is not None and self._manager is not None
        powered = _variant_bool(self._adapter.get_cached_property("Powered"), False)
        discovering = _variant_bool(self._adapter.get_cached_property("Discovering"), False)
        adapter_name = _variant_str(self._adapter.get_cached_property("Alias")) or _variant_str(
            self._adapter.get_cached_property("Name"),
        )
        adapter_address = _variant_str(self._adapter.get_cached_property("Address"))

        managed = self._manager.call_sync(
            "GetManagedObjects",
            None,
            Gio.DBusCallFlags.NONE,
            _DBUS_TIMEOUT_MS,
            None,
        )
        objects = managed.unpack()[0] if managed is not None else {}
        devices: list[BluetoothDeviceSnapshot] = []
        for path, ifaces in objects.items():
            props = ifaces.get(DEVICE_IFACE)
            if not props:
                continue
            battery = ifaces.get(BATTERY_IFACE) or {}
            address = _variant_str(props.get("Address"))
            name = _variant_str(props.get("Name"))
            alias = _variant_str(props.get("Alias"))
            devices.append(
                BluetoothDeviceSnapshot(
                    path=str(path),
                    address=address,
                    name=name,
                    alias=alias,
                    icon=_variant_str(props.get("Icon")),
                    paired=_variant_bool(props.get("Paired")),
                    connected=_variant_bool(props.get("Connected")),
                    trusted=_variant_bool(props.get("Trusted")),
                    connecting=str(path) in self._busy_paths,
                    battery_percent=_variant_int(battery.get("Percentage")),
                )
            )

        devices.sort(
            key=lambda d: (
                0 if d.connected else 1 if d.paired else 2,
                (d.alias or d.name or d.address).casefold(),
            )
        )

        if not powered:
            status = "Bluetooth desactivado"
        elif discovering:
            status = "Buscando dispositivos…"
        elif any(d.connected for d in devices):
            status = "Conectado"
        else:
            status = "Activado"

        return BluetoothSnapshot(
            available=True,
            powered=powered,
            discovering=discovering,
            adapter_name=adapter_name,
            adapter_address=adapter_address,
            devices=tuple(devices),
            status_message=status,
            error_message="",
        )

    def _publish(self, snapshot: BluetoothSnapshot) -> None:
        if self._emitted_once and snapshot == self._snapshot:
            return
        self._emitted_once = True
        self._snapshot = snapshot
        self._event_bus.emit(BLUETOOTH_CHANGED, snapshot)


def _friendly_bluez_error(error: Exception) -> str:
    text = str(error)
    lowered = text.casefold()
    if "authenticationcanceled" in lowered or "canceled" in lowered:
        return "Emparejamiento cancelado"
    if "authenticationfailed" in lowered:
        return "Falló la autenticación Bluetooth"
    if "alreadyconnected" in lowered:
        return "El dispositivo ya está conectado"
    if "notinprogress" in lowered:
        return ""
    if "failed" in lowered and "connect" in lowered:
        return "No se pudo conectar. Acerca el dispositivo e inténtalo de nuevo."
    # Keep message short for the panel.
    compact = text.split(":", 1)[-1].strip() or text
    return compact[:160]
