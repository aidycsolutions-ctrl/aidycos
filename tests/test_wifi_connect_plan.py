from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_plan():
    path = (
        ROOT
        / "packaging"
        / "jugoo-overlay"
        / "shell"
        / "servicios"
        / "red"
        / "wifi_connect_plan.py"
    )
    spec = importlib.util.spec_from_file_location("wifi_connect_plan", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WifiConnectPlanTests(unittest.TestCase):
    def test_switch_network_disconnects_current_first(self) -> None:
        plan = _load_plan()
        commands, ignore = plan.plan_wifi_connect_commands(
            ssid="Other",
            interface="wlp1s0",
            password="secret",
            saved_uuids=(),
            current_ssid="Home",
            currently_connected=True,
        )
        self.assertEqual(
            commands[0],
            ["--wait", "15", "device", "disconnect", "wlp1s0"],
        )
        self.assertEqual(
            commands[1],
            [
                "--wait",
                "30",
                "device",
                "wifi",
                "connect",
                "Other",
                "ifname",
                "wlp1s0",
                "password",
                "secret",
            ],
        )
        self.assertEqual(ignore, 1)

    def test_saved_profile_up_without_disconnect_when_same_ssid(self) -> None:
        plan = _load_plan()
        commands, ignore = plan.plan_wifi_connect_commands(
            ssid="Home",
            interface="wlp1s0",
            password="",
            saved_uuids=("uuid-1",),
            current_ssid="Home",
            currently_connected=True,
        )
        self.assertEqual(
            commands,
            [["--wait", "30", "connection", "up", "uuid", "uuid-1", "ifname", "wlp1s0"]],
        )
        self.assertEqual(ignore, 0)

    def test_blank_secured_profile_is_not_saved(self) -> None:
        plan = _load_plan()
        self.assertFalse(
            plan.access_point_counts_as_saved(
                ssid="Cafe",
                secured=True,
                profile_ssids={"Cafe"},
                secrets_ssids=set(),
            )
        )
        self.assertTrue(
            plan.access_point_counts_as_saved(
                ssid="Cafe",
                secured=True,
                profile_ssids={"Cafe"},
                secrets_ssids={"Cafe"},
            )
        )
        self.assertTrue(
            plan.access_point_counts_as_saved(
                ssid="Open",
                secured=False,
                profile_ssids={"Open"},
                secrets_ssids=set(),
            )
        )


if __name__ == "__main__":
    unittest.main()
