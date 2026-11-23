"""El comando de AidyCOS abre la XPRINTER por usblp y no dispara el cajón en una prueba."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "scripts" / "aidycos-cajon"
    loader = importlib.machinery.SourceFileLoader("aidycos_cajon", str(path))
    spec = importlib.util.spec_from_loader("aidycos_cajon", loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DrawerCommandTests(unittest.TestCase):
    def test_pulse_matches_the_usblp_sequence(self) -> None:
        cajon = _load()
        self.assertEqual(cajon.DRAWER_PULSE, bytes([0x1B, 0x70, 0x00, 0x19, 0xFA]))
        self.assertTrue(hasattr(cajon, "openCashDrawer"))

    def test_hp_is_never_selected(self) -> None:
        cajon = _load()
        available = ["HP_Smart_Tank_WiFi", "XPRINTER"]
        self.assertEqual(cajon.resolve_drawer_printer(None, available), "XPRINTER")
        self.assertEqual(
            cajon.resolve_drawer_printer("HP_Smart_Tank_WiFi", available),
            "XPRINTER",
        )
        self.assertEqual(
            cajon.resolve_drawer_printer(None, ["HP_Smart_Tank_WiFi"]),
            "XPRINTER",
        )

    def test_dry_run_does_not_call_cups(self) -> None:
        cajon = _load()
        with mock.patch.object(cajon.subprocess, "run") as run:
            opened, detail = cajon.open_drawer(dry_run=True, available=["XPRINTER"])
        self.assertTrue(opened)
        self.assertIn("dry-run", detail)
        run.assert_not_called()

    def test_open_writes_escpos_without_lp(self) -> None:
        cajon = _load()
        with tempfile.TemporaryDirectory() as temp:
            port = Path(temp) / "lp0"
            port.write_bytes(b"")
            with mock.patch.object(cajon.subprocess, "run") as run:
                opened, detail = cajon.openCashDrawer(device=str(port), timeout=0.5)
            run.assert_not_called()
            self.assertTrue(opened)
            self.assertEqual(detail, str(port))
            self.assertEqual(port.read_bytes(), bytes([0x1B, 0x70, 0x00, 0x19, 0xFA]))

    def test_open_drawer_delegates_to_the_port(self) -> None:
        cajon = _load()
        with tempfile.TemporaryDirectory() as temp:
            port = Path(temp) / "lp0"
            port.write_bytes(b"")
            opened, detail = cajon.open_drawer(
                available=["HP_Smart_Tank_WiFi", "XPRINTER"],
                device=str(port),
            )
            self.assertTrue(opened)
            self.assertEqual(detail, str(port))
            self.assertEqual(port.read_bytes(), cajon.DRAWER_PULSE)

    def test_falls_back_to_the_next_usblp_node(self) -> None:
        cajon = _load()
        with tempfile.TemporaryDirectory() as temp:
            lp1 = Path(temp) / "lp1"
            lp1.write_bytes(b"")
            devices = ("/dev/usb/lp0", str(lp1))

            def exists(path: str) -> bool:
                return path == str(lp1)

            with (
                mock.patch.object(cajon, "DRAWER_DEVICES", devices),
                mock.patch.object(cajon.os.path, "exists", side_effect=exists),
                mock.patch.object(cajon.glob, "glob", return_value=[]),
            ):
                opened, detail = cajon.openCashDrawer(timeout=0.5)
            self.assertTrue(opened)
            self.assertEqual(detail, str(lp1))
            self.assertEqual(lp1.read_bytes(), cajon.DRAWER_PULSE)

    def test_timeout_is_logged_and_does_not_raise(self) -> None:
        cajon = _load()
        with tempfile.TemporaryDirectory() as temp:
            port = Path(temp) / "lp0"
            port.write_bytes(b"")
            with mock.patch.object(cajon.select, "select", return_value=([], [], [])):
                with self.assertLogs("aidycos.cajon", level="ERROR"):
                    opened, detail = cajon.openCashDrawer(device=str(port), timeout=0.05)
            self.assertFalse(opened)
            self.assertIn("no aceptó", detail)
            self.assertEqual(port.read_bytes(), b"")

    def test_missing_port_is_logged(self) -> None:
        cajon = _load()
        missing = "/dev/usb/does-not-exist-aidycos"
        with self.assertLogs("aidycos.cajon", level="ERROR"):
            opened, detail = cajon.openCashDrawer(device=missing, timeout=0.05)
        self.assertFalse(opened)
        self.assertIn(missing, detail)

    def test_write_error_is_logged_not_raised(self) -> None:
        cajon = _load()
        with tempfile.TemporaryDirectory() as temp:
            port = Path(temp) / "lp0"
            port.write_bytes(b"")
            with mock.patch.object(cajon.os, "write", side_effect=OSError(5, "Input/output error")):
                with self.assertLogs("aidycos.cajon", level="ERROR"):
                    opened, detail = cajon.openCashDrawer(device=str(port), timeout=0.5)
        self.assertFalse(opened)
        self.assertIn("Input/output error", detail)

    def test_factura_opens_once_and_test_pages_do_not(self) -> None:
        cajon = _load()
        sample = "\n".join(
            [
                "XPRINTER-4  caja  512  lun 23 nov 2026 12:00:00",
                "\ten cola para XPRINTER",
                "\tFactura-E",
                "XPRINTER-5  caja  5  lun 23 nov 2026 12:00:02",
                "\ten cola para XPRINTER",
                "\tOpen Drawer",
                "XPRINTER-6  caja  80  lun 23 nov 2026 12:00:03",
                "\tqueued for XPRINTER",
                "\tPágina de prueba",
            ]
        )
        jobs = cajon.parse_completed_jobs(sample)
        self.assertEqual(
            [title for _key, _size, title in jobs],
            ["Factura-E", "Open Drawer", "Página de prueba"],
        )
        seen, fresh = cajon.kicks_for_new_jobs(None, jobs)
        self.assertEqual(fresh, [])
        seen, fresh = cajon.kicks_for_new_jobs(seen, jobs)
        self.assertEqual(fresh, [])
        extra = jobs + [
            ("XPRINTER-7  caja  400  lun 23 nov 2026 12:01:00", 400, "Ticket"),
            ("XPRINTER-8  caja  5  lun 23 nov 2026 12:01:01", 5, ""),
        ]
        seen, fresh = cajon.kicks_for_new_jobs(seen, extra)
        self.assertEqual([title for _key, _size, title in fresh], ["Ticket"])
        self.assertTrue(cajon.should_open_after_print("Factura-E", 512))
        self.assertFalse(cajon.should_open_after_print("Open Drawer", 5))
        self.assertFalse(cajon.should_open_after_print("", 5))
        self.assertFalse(cajon.should_open_after_print("Test Page", 800))
        self.assertFalse(cajon.should_open_after_print("Página de prueba", 80))

    def test_clear_removes_stuck_open_drawer_jobs_shown_as_zero(self) -> None:
        cajon = _load()
        sample = "\n".join(
            [
                "XPRINTER-359  Desconocido  0  lun 23 nov 2026 13:12:00",
                "\tOpen Drawer",
                "XPRINTER-360  Desconocido  0  lun 23 nov 2026 13:12:01",
                "\tOpen Drawer",
                "XPRINTER-361  caja  800  lun 23 nov 2026 13:12:02",
                "\tFactura-E",
            ]
        )
        calls: list[list[str]] = []

        def fake_run(argv, **_kwargs):
            calls.append(list(argv))
            if str(argv[0]).endswith("lpstat"):
                return subprocess.CompletedProcess(argv, 0, sample, "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        removed = cajon.cancel_pulse_jobs("XPRINTER", run=fake_run)
        self.assertEqual(removed, ["XPRINTER-359", "XPRINTER-360"])
        cancelled = [cmd for cmd in calls if "cancel" in str(cmd[0])]
        self.assertEqual(len(cancelled), 2)
        self.assertTrue(all("-x" in cmd for cmd in cancelled))

    def test_session_config_adds_f6_and_watcher_once(self) -> None:
        cajon = _load()
        command = "/usr/local/bin/aidycos-cajon"
        once = cajon.ensure_session_config("bind = ALT, F4, exec, jugoo action session\n", command)
        twice = cajon.ensure_session_config(once, command)
        self.assertEqual(once, twice)
        self.assertEqual(once.count("bind = , F6, exec, /usr/local/bin/aidycos-cajon"), 1)
        self.assertIn("exec-once = /usr/local/bin/aidycos-cajon watch", once)

    def test_installer_ships_the_command(self) -> None:
        text = (ROOT / "scripts" / "install-debian-profile.sh").read_text(encoding="utf-8")
        self.assertIn("/usr/local/bin/aidycos-cajon", text)
        self.assertIn("aidycos-cajon.desktop", text)
        self.assertIn("bind = , F6, exec, /usr/local/bin/aidycos-cajon", text)
        self.assertIn("aidycos-cajon watch", text)
        self.assertIn("/etc/modules-load.d/usblp.conf", text)
        self.assertIn("modprobe usblp", text)
        self.assertIn("/etc/udev/rules.d/99-xprinter-nosuspend.rules", text)
        self.assertIn(
            'ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="070b", MODE="0666", TEST=="power/control", ATTR{power/control}="on"',
            text,
        )
        self.assertIn("udevadm control --reload-rules", text)
        self.assertIn("udevadm trigger", text)
        self.assertIn("usermod -aG lp", text)
        uninstall = (ROOT / "scripts" / "uninstall-debian-profile.sh").read_text(encoding="utf-8")
        self.assertIn("99-xprinter-nosuspend.rules", uninstall)
        self.assertIn("usblp.conf", uninstall)


if __name__ == "__main__":
    unittest.main()
