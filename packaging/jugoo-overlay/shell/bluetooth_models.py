"""Snippets used to patch Jugoo ``shell/models.py`` for Bluetooth snapshots."""

BLUETOOTH_MODELS_SNIPPET = '''@dataclass(frozen=True)
class BluetoothDeviceSnapshot:
    """One BlueZ device (paired, connected, or discovered)."""

    path: str
    address: str
    name: str
    alias: str = ""
    icon: str = ""
    paired: bool = False
    connected: bool = False
    trusted: bool = False
    connecting: bool = False
    battery_percent: int | None = None


@dataclass(frozen=True)
class BluetoothSnapshot:
    """Adapter + device list for the Bluetooth control-center section."""

    available: bool = False
    powered: bool = False
    discovering: bool = False
    adapter_name: str = ""
    adapter_address: str = ""
    devices: tuple["BluetoothDeviceSnapshot", ...] = ()
    status_message: str = ""
    error_message: str = ""

    @classmethod
    def unavailable(cls, message: str = "Bluetooth no disponible") -> "BluetoothSnapshot":
        return cls(available=False, status_message=message)
'''
