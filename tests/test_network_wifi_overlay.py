from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_overlay():
    spec = importlib.util.spec_from_file_location(
        "jugoo_overlay_install",
        ROOT / "packaging" / "jugoo-overlay" / "install.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD_NETWORK_PY = '''"""Minimal stub of an older Jugoo NetworkService without Wi-Fi share/forget."""

class NetworkService:
    def toggle_ethernet(self) -> None:
        pass

    def set_wireless_enabled(self, enabled: bool) -> None:
        pass

    def request_wifi_scan(self) -> None:
        pass

    def connect_wifi(self, path: str, password: str = "") -> None:
        pass

    def disconnect_wifi(self) -> None:
        pass
'''

OLD_NETWORK_SECTION_PY = '''"""Minimal stub without Compartir / Olvidar actions."""

class ControlCenterNetworkSection:
    def __init__(
        self,
        network_service,
        *,
        on_toggle_ethernet,
        on_toggle_wireless,
        on_request_wifi_scan,
        on_connect_wifi,
        on_disconnect_wifi,
        on_toggle_hotspot,
        on_apply_hotspot,
    ):
        self._network_service = network_service
'''

OLD_MODELS_PY = '''from dataclasses import dataclass


@dataclass(frozen=True)
class WifiAccessPointSnapshot:
    """One scanned Wi-Fi access point."""

    path: str
    ssid: str
    strength: int
    secured: bool
    frequency_mhz: int
    active: bool = False


@dataclass(frozen=True)
class HotspotClientSnapshot:
    """One station associated with the local AP, as reported by NetworkManager."""

    mac_address: str
'''

OLD_POPUP_PY = '''from .network_section import ControlCenterNetworkSection


class ControlCenterPopup:
    def __init__(self, network_service, view):
        if view in ("full", "network"):
            self._network_section = ControlCenterNetworkSection(
                network_service,
                on_toggle_ethernet=network_service.toggle_ethernet,
                on_toggle_wireless=network_service.set_wireless_enabled,
                on_request_wifi_scan=network_service.request_wifi_scan,
                on_connect_wifi=lambda path, password: network_service.connect_wifi(
                    path,
                    password,
                ),
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
            )
'''


class NetworkWifiOverlayTests(unittest.TestCase):
    def test_overlay_installs_wifi_share_forget(self) -> None:
        overlay = _load_overlay()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            network = root / "shell/servicios/red/network.py"
            hotspot = root / "shell/servicios/red/network_hotspot.py"
            section = root / "shell/widgets/centro_control/network_section.py"
            models = root / "shell/models.py"
            popup = root / "shell/widgets/centro_control/popup.py"
            style = root / "shell/style.css"
            for path in (network, hotspot, section, models, popup, style):
                path.parent.mkdir(parents=True, exist_ok=True)

            network.write_text(OLD_NETWORK_PY, encoding="utf-8")
            hotspot.write_text("# old hotspot stub\n", encoding="utf-8")
            section.write_text(OLD_NETWORK_SECTION_PY, encoding="utf-8")
            models.write_text(OLD_MODELS_PY, encoding="utf-8")
            popup.write_text(OLD_POPUP_PY, encoding="utf-8")
            style.write_text("/* base */\n", encoding="utf-8")

            overlay.install_network_wifi(root)

            network_text = network.read_text(encoding="utf-8")
            self.assertIn("def forget_wifi", network_text)
            self.assertIn("WifiCredentials", network_text)

            section_text = section.read_text(encoding="utf-8")
            self.assertIn("Compartir", section_text)
            self.assertIn("Olvidar", section_text)

            models_text = models.read_text(encoding="utf-8")
            self.assertIn("class WifiCredentials:", models_text)
            self.assertIn("saved: bool = False", models_text)

            popup_text = popup.read_text(encoding="utf-8")
            self.assertIn("on_forget_wifi=network_service.forget_wifi", popup_text)
            self.assertIn(
                "on_request_wifi_credentials=network_service.request_active_wifi_credentials",
                popup_text,
            )

            style_text = style.read_text(encoding="utf-8")
            self.assertIn("control-center-wifi-share", style_text)
            self.assertIn("control-center-wifi-list", style_text)


if __name__ == "__main__":
    unittest.main()
