"""Checks that AidyCOS updates install AidyLink's delayed user service."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
AIDYLINK = ROOT / "packaging/aidylink"
sys.path.insert(0, str(AIDYLINK))
from aidylink.cloud import AidyChatBridge  # noqa: E402


def parse_unit(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "[")) and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


class AidyLinkBackgroundServiceTests(unittest.TestCase):
    def test_timer_delays_daemon_after_graphical_session(self) -> None:
        timer = parse_unit(AIDYLINK / "aidylink.timer")
        self.assertEqual(timer["OnActiveSec"], "20s")
        self.assertEqual(timer["Unit"], "aidylink.service")
        self.assertEqual(timer["WantedBy"], "default.target")
        self.assertEqual(timer["Wants"], "graphical-session.target")
        self.assertEqual(timer["After"], "graphical-session.target")

    def test_service_is_headless_restartable_and_stops_with_user_session(self) -> None:
        service = parse_unit(AIDYLINK / "aidylink.service")
        self.assertEqual(service["ExecStart"], "/usr/local/bin/aidylink daemon")
        self.assertEqual(service["Restart"], "on-failure")
        self.assertEqual(service["PartOf"], "default.target")
        self.assertEqual(service["TimeoutStopSec"], "15s")

    def test_profile_and_app_updates_migrate_old_service_to_timer(self) -> None:
        profile = (ROOT / "scripts/install-debian-profile.sh").read_text(encoding="utf-8")
        app_update = (ROOT / "scripts/actualizar-aidylink.sh").read_text(encoding="utf-8")
        auto_update = (ROOT / "scripts/aidycos-update").read_text(encoding="utf-8")
        for script in (profile, app_update):
            self.assertIn("aidylink.timer", script)
            self.assertIn('rm -f "${wants_dir}/aidylink.service"', script)
            self.assertIn("enable --now aidylink.timer", script)
            self.assertIn("is-active --quiet aidylink.service", script)
        self.assertIn('installer=\"\\${source_dir}/scripts/install-debian-profile.sh\"', auto_update)

    def test_cloud_poll_resumes_after_an_empty_offline_cycle(self) -> None:
        class FakeBridge:
            enabled = True

            def __init__(self) -> None:
                self.poll_count = 0

            def poll_once(self) -> list[str]:
                self.poll_count += 1
                return [] if self.poll_count == 1 else ["mensaje"]

        class StopPolling(Exception):
            pass

        bridge = FakeBridge()
        delivered: list[list[str]] = []
        sleep_count = 0

        async def in_thread(function):
            return function()

        async def wait_next(_interval: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count == 2:
                raise StopPolling

        async def exercise() -> None:
            with mock.patch("asyncio.to_thread", side_effect=in_thread), mock.patch(
                "asyncio.sleep", side_effect=wait_next
            ):
                await AidyChatBridge.poll_loop(bridge, 0.01, delivered.append)

        with self.assertRaises(StopPolling):
            asyncio.run(exercise())
        self.assertEqual(bridge.poll_count, 2)
        self.assertEqual(delivered, [["mensaje"]])


if __name__ == "__main__":
    unittest.main()
