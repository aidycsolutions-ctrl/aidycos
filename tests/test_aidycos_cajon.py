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

    def test_installer_ships_the_command(self) -> None:
        text = (ROOT / "scripts" / "install-debian-profile.sh").read_text(encoding="utf-8")
        self.assertIn("/usr/local/bin/aidycos-cajon", text)
        self.assertIn("aidycos-cajon.desktop", text)


if __name__ == "__main__":
    unittest.main()
