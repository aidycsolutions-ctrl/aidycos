"""Bluetooth overlay: models, helpers, and Jugoo install wiring."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "packaging" / "jugoo-overlay"
SERVICE = OVERLAY / "shell" / "servicios" / "bluetooth" / "service.py"


def _load_overlay():
    spec = importlib.util.spec_from_file_location(
        "jugoo_overlay_install",
        OVERLAY / "install.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_service_helpers():
    spec = importlib.util.spec_from_file_location("aidycos_bt_service", SERVICE)
    assert spec and spec.loader
    # Avoid importing GI-heavy module body for pure helpers: exec selected pieces.
    text = SERVICE.read_text(encoding="utf-8")
    ns: dict = {}
    # Minimal stubs so helper functions can be exec'd without Gio.
    exec("from __future__ import annotations\n", ns)
    # Pull only pure functions by compiling the module after stubbing gi.
    import sys
    import types

    gi = types.ModuleType("gi")
    gi.require_version = lambda *a, **k: None
    repository = types.ModuleType("gi.repository")

    class _Dummy:
        pass

    repository.Gio = _Dummy
    repository.GLib = _Dummy
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository
    # models stub
    models = types.ModuleType("models")

    class BluetoothDeviceSnapshot:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class BluetoothSnapshot:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        @classmethod
        def unavailable(cls, message=""):
            return cls(available=False, status_message=message, devices=(), powered=False)

    models.BluetoothDeviceSnapshot = BluetoothDeviceSnapshot
    models.BluetoothSnapshot = BluetoothSnapshot
    # Fake package hierarchy for relative imports inside service.py
    shell_pkg = types.ModuleType("shell")
    shell_pkg.__path__ = []
    sys.modules["shell"] = shell_pkg
    sys.modules["shell.models"] = models
    eventbus = types.ModuleType("shell.eventbus")

    class EventBus:
        pass

    eventbus.EventBus = EventBus
    sys.modules["shell.eventbus"] = eventbus
    # Rewrite relative imports for isolated load
    patched = text.replace("from ...eventbus", "from shell.eventbus").replace(
        "from ...models",
        "from shell.models",
    )
    mod = types.ModuleType("bt_service_isolated")
    exec(compile(patched, str(SERVICE), "exec"), mod.__dict__)
    return mod


class BluetoothHelperTests(unittest.TestCase):
    def test_icon_and_tooltip_helpers(self) -> None:
        mod = _load_service_helpers()
        Snap = mod.BluetoothSnapshot
        Dev = mod.BluetoothDeviceSnapshot
        off = Snap(available=True, powered=False, devices=(), status_message="")
        self.assertEqual(mod.bluetooth_bar_icon_name(off), "bluetooth-disabled-symbolic")
        self.assertIn("desactivado", mod.bluetooth_bar_tooltip(off).casefold())
        connected = Snap(
            available=True,
            powered=True,
            devices=(Dev(path="/x", address="AA", name="Auriculares", alias="Auriculares", connected=True),),
            status_message="",
        )
        self.assertEqual(mod.bluetooth_bar_icon_name(connected), "bluetooth-active-symbolic")
        self.assertIn("Auriculares", mod.bluetooth_bar_tooltip(connected))


class BluetoothOverlayInstallTests(unittest.TestCase):
    def test_install_bluetooth_wires_app(self) -> None:
        overlay = _load_overlay()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "jugoo"
            shell = root / "shell"
            (shell / "servicios" / "red").mkdir(parents=True)
            (shell / "widgets" / "barra").mkdir(parents=True)
            (shell / "widgets" / "centro_control").mkdir(parents=True)
            (shell / "controllers").mkdir(parents=True)
            (shell / "models.py").write_text(
                "from dataclasses import dataclass\n\n"
                "@dataclass(frozen=True)\nclass NetworkInterfaceSnapshot:\n"
                "    name: str = ''\n",
                encoding="utf-8",
            )
            (shell / "style.css").write_text("/* style */\n", encoding="utf-8")
            (shell / "app.py").write_text(
                "from .servicios.red.network import NetworkService\n"
                "from .widgets.barra.ethernet import EthernetWidget\n"
                "from .controllers.control_center import ControlCenterController\n"
                "\n"
                "class App:\n"
                "    def __init__(self):\n"
                "        self.event_bus = None\n"
                "        self.network_service = NetworkService(self.event_bus)\n"
                "        self.ethernet_widget = EthernetWidget(self.event_bus, self.network_service)\n"
                "        self.power_widget = None\n"
                "        self.layout = type('L', (), {'right': type('R', (), {'add': lambda *a, **k: None})()})()\n"
                "        self.layout.right.add(self.ethernet_widget)\n"
                "        self.control_center_controller = ControlCenterController(\n"
                "            self.event_bus,\n"
                "            self.network_service,\n"
                "            self.ethernet_widget,\n"
                "            self.power_widget,\n"
                "            self,\n"
                "        )\n"
                "\n"
                "    def start(self):\n"
                "        self.hyprland.start()\n"
                "\n"
                "    def close(self):\n"
                "        self.network_service.close()\n",
                encoding="utf-8",
            )
            # Minimal stubs so install_overlay_file sources exist conceptually.
            overlay.install_bluetooth(root)
            app = (shell / "app.py").read_text(encoding="utf-8")
            models = (shell / "models.py").read_text(encoding="utf-8")
            self.assertIn("BluetoothService", app)
            self.assertIn("bluetooth_widget", app)
            self.assertIn("bluetooth_service=self.bluetooth_service", app)
            self.assertIn("class BluetoothSnapshot:", models)
            self.assertTrue((shell / "servicios/bluetooth/service.py").is_file())
            self.assertTrue((shell / "widgets/barra/bluetooth.py").is_file())
            self.assertTrue((shell / "widgets/centro_control/bluetooth_section.py").is_file())


class InstallerBluetoothPackageTests(unittest.TestCase):
    def test_profile_enables_bluez(self) -> None:
        text = (ROOT / "scripts" / "install-debian-profile.sh").read_text(encoding="utf-8")
        self.assertIn("bluetooth.service", text)
        self.assertIn("bluez", text)
        self.assertIn("install_bluetooth", (OVERLAY / "install.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
