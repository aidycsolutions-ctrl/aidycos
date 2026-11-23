"""El comando de AidyCOS abre la XPRINTER y no dispara el cajón en una prueba."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
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
    def test_pulse_matches_the_working_printf(self) -> None:
        cajon = _load()
        self.assertEqual(cajon.DRAWER_PULSE, bytes([27, 112, 1, 37, 250]))

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

    def test_open_sends_raw_pulse_and_confirms_the_job(self) -> None:
        cajon = _load()
        seen: dict[str, object] = {}

        def fake_run(argv, **kwargs):
            tool = str(argv[0])
            if tool.endswith("/lp") or tool == "lp":
                seen["argv"] = list(argv)
                seen["payload"] = kwargs.get("input")
                return subprocess.CompletedProcess(
                    argv, 0, "request id is XPRINTER-4 (1 file(s))\n", ""
                )
            return subprocess.CompletedProcess(argv, 0, "", "")

        opened, detail = cajon.open_drawer(available=["HP_Smart_Tank_WiFi", "XPRINTER"], run=fake_run)
        self.assertTrue(opened)
        self.assertEqual(detail, "XPRINTER-4")
        self.assertEqual(seen["payload"], bytes([27, 112, 1, 37, 250]))
        argv = seen["argv"]
        assert isinstance(argv, list)
        self.assertEqual(argv[1:5], ["-d", "XPRINTER", "-o", "raw"])

    def test_rejected_job_is_reported(self) -> None:
        cajon = _load()

        def fake_run(argv, **_kwargs):
            return subprocess.CompletedProcess(argv, 1, "", "lp: The printer or class does not exist.")

        with self.assertLogs("aidycos.cajon", level="ERROR"):
            opened, detail = cajon.open_drawer(available=["XPRINTER"], run=fake_run)
        self.assertFalse(opened)
        self.assertIn("does not exist", detail)

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


if __name__ == "__main__":
    unittest.main()
