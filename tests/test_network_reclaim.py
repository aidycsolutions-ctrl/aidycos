from __future__ import annotations

import re
import stat
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NETWORK = ROOT / "packaging" / "network"
APPLY = NETWORK / "apply-aidycos-network.sh"
RECLAIM = NETWORK / "aidycos-wifi-reclaim.sh"
SERVICE = NETWORK / "aidycos-wifi-reclaim.service"
INSTALLER = ROOT / "scripts" / "install-debian-profile.sh"


class NetworkReclaimTests(unittest.TestCase):
    def test_installer_calls_network_apply(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("packaging/network/apply-aidycos-network.sh", text)

    def test_reclaim_script_and_unit_exist(self) -> None:
        self.assertTrue(RECLAIM.is_file())
        self.assertTrue(SERVICE.is_file())
        self.assertTrue(RECLAIM.stat().st_mode & stat.S_IXUSR)
        self.assertTrue(APPLY.stat().st_mode & stat.S_IXUSR)

    def test_service_unit_is_oneshot_after_networkmanager(self) -> None:
        text = SERVICE.read_text(encoding="utf-8")
        self.assertIn("Type=oneshot", text)
        self.assertIn("After=NetworkManager.service", text)
        self.assertIn("Wants=NetworkManager.service", text)
        self.assertIn("RemainAfterExit=yes", text)
        self.assertIn(
            "ExecStart=/usr/local/libexec/aidycos/aidycos-wifi-reclaim.sh",
            text,
        )

    def test_reclaim_gates_bounce_and_spares_dbus_wpa(self) -> None:
        text = RECLAIM.read_text(encoding="utf-8")
        self.assertIn("NetworkManager", text)
        self.assertIn("unavailable", text)
        self.assertIn("unmanaged", text)
        self.assertIn("ip link set", text)
        self.assertIn("bounce_wifi_iface", text)
        self.assertIn("connection.autoconnect yes", text)
        self.assertIn("rfkill unblock", text)
        # Orphan / ifupdown-style only; must not mask the D-Bus unit.
        self.assertIn("/etc/wpa_supplicant", text)
        self.assertNotIn("mask wpa_supplicant.service", text)
        self.assertNotIn("disable wpa_supplicant.service", text)
        self.assertNotRegex(
            text,
            re.compile(r"systemctl\s+(mask|disable).*[^@]wpa_supplicant\.service"),
        )

    def test_apply_skips_blank_psk_and_masks_only_template(self) -> None:
        text = APPLY.read_text(encoding="utf-8")
        self.assertIn("aidycos-wifi-reclaim.sh", text)
        self.assertIn("aidycos-wifi-reclaim.service", text)
        self.assertIn("99-aidycos-wifi.conf", text)
        self.assertIn("wifi.scan-rand-mac-address=no", text)
        self.assertIn("systemctl mask networking.service", text)
        self.assertIn("wpa_supplicant@.service", text)
        self.assertIn("mask 'wpa_supplicant@.service'", text)
        self.assertIn("Never create a blank/PSK-less profile", text)
        self.assertIn("reclaim_bounce_wifi_once", text)
        self.assertIn("ensure_wifi_autoconnect", text)
        # Must not mask/disable the plain D-Bus wpa_supplicant.service.
        self.assertNotIn("mask wpa_supplicant.service", text)
        self.assertNotIn('mask "wpa_supplicant.service"', text)
        self.assertIn(
            "Do NOT touch wpa_supplicant.service",
            text,
        )
        # adopt path must not invent empty-PSK connections
        self.assertIn("never invent a blank PSK connection", text)
        create_fn_start = text.index("create_nm_wifi_connection() {")
        create_fn_end = text.index("\n}\n", create_fn_start)
        create_fn = text[create_fn_start:create_fn_end]
        self.assertIn('[[ -z "${psk}" ]]', create_fn)
        self.assertIn("return 0", create_fn)


if __name__ == "__main__":
    unittest.main()
