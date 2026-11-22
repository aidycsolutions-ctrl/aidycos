"""New window commands for apps already open on another escritorio."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_overlay_install():
    spec = importlib.util.spec_from_file_location(
        "jugoo_overlay_install_new_instance",
        ROOT / "packaging" / "jugoo-overlay" / "install.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NewInstanceOtherDesktopTests(unittest.TestCase):
    def test_onlyoffice_desktop_declares_wm_class_and_new_window(self) -> None:
        text = (
            ROOT / "packaging" / "applications" / "aidycos-onlyoffice.desktop"
        ).read_text(encoding="utf-8")
        self.assertIn("StartupWMClass=ONLYOFFICE", text)
        self.assertIn("Exec=aidycos-onlyoffice --new:word", text)

    def test_onlyoffice_wrapper_translates_new_window(self) -> None:
        text = (ROOT / "scripts" / "aidycos-onlyoffice").read_text(encoding="utf-8")
        self.assertIn("--new-window|--new-instance)", text)
        self.assertIn("ARGS+=(--new:word)", text)

    def test_overlay_teaches_models_onlyoffice_flag(self) -> None:
        overlay = _load_overlay_install()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            models = root / "shell" / "models.py"
            models.parent.mkdir(parents=True)
            models.write_text(
                "_NEW_WINDOW_FLAGS = (\"--new-window\", \"--new-instance\", \"-new-window\")\n"
                "\n"
                "\n"
                "def new_instance_command(application: DesktopApplication) -> str:\n"
                "    \"\"\"Best-effort command that asks the app for a fresh window/instance.\"\"\"\n"
                "    if application.new_instance_exec.strip():\n"
                "        return application.new_instance_exec.strip()\n"
                "    command = application.exec_cmd.strip()\n"
                "    if not command:\n"
                "        return \"\"\n"
                "    if any(flag in command for flag in _NEW_WINDOW_FLAGS) or application.terminal:\n"
                "        return command\n"
                "    return f\"{command} --new-window\"\n",
                encoding="utf-8",
            )
            overlay.install_new_instance_on_other_desktops(root)
            text = models.read_text(encoding="utf-8")
            self.assertIn("_ONLYOFFICE_KEYS", text)
            self.assertIn("--new:word", text)
            overlay.install_new_instance_on_other_desktops(root)
            self.assertEqual(text, models.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
