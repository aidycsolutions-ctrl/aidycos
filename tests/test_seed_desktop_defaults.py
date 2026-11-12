from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "seed_desktop_defaults",
    ROOT / "scripts" / "seed-desktop-defaults.py",
)
assert SPEC and SPEC.loader
seed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed)


class SeedDesktopDefaultsTests(unittest.TestCase):
    def test_empty_or_missing_icons_are_seeded_and_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            data = home / ".local" / "share" / "waybar-shell"
            apps = home / ".local" / "share" / "applications"
            data.mkdir(parents=True)
            apps.mkdir(parents=True)
            for name in (
                "aidychat.desktop",
                "firefox-esr.desktop",
                "foot.desktop",
                "aidycos-paquetes.desktop",
                "aidycos-onlyoffice.desktop",
            ):
                (apps / name).write_text(
                    "[Desktop Entry]\nType=Application\nName=Test\n",
                    encoding="utf-8",
                )

            icons_path = data / "desktop-icons.json"
            settings_path = data / "settings.json"
            settings_path.write_text(
                json.dumps({"version": 1, "values": {"escritorio.icons_enabled": False}})
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ,
                {"HOME": str(home), "XDG_DATA_HOME": str(home / ".local" / "share")},
                clear=False,
            ):
                self.assertTrue(
                    seed.ensure_desktop_icons(icons_path, home=home, reset=False, clear=False)
                )
                payload = json.loads(icons_path.read_text(encoding="utf-8"))
                names = [item["name"] for item in payload["icons"]]
                self.assertIn("AidyChat", names)
                self.assertIn("OnlyOffice", names)
                self.assertIn("Instalar paquetes", names)

                # Preserve custom icons on later updates when defaults already exist.
                self.assertFalse(
                    seed.ensure_desktop_icons(icons_path, home=home, reset=False, clear=False)
                )

                # Default seed path keeps the icon layer disabled.
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                settings["values"]["escritorio.icons_enabled"] = True
                settings_path.write_text(
                    json.dumps(settings, indent=2) + "\n", encoding="utf-8"
                )
                self.assertTrue(seed.ensure_icons_disabled(settings_path))
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                self.assertFalse(settings["values"]["escritorio.icons_enabled"])
                self.assertFalse(seed.ensure_icons_disabled(settings_path))

                # Legacy enable helper still works when forced.
                self.assertTrue(seed.ensure_icons_enabled(settings_path, force=True))
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                self.assertTrue(settings["values"]["escritorio.icons_enabled"])
                settings["values"]["escritorio.icons_enabled"] = False
                settings_path.write_text(
                    json.dumps(settings, indent=2) + "\n", encoding="utf-8"
                )
                self.assertFalse(seed.ensure_icons_enabled(settings_path, force=False))

    def test_missing_firefox_is_merged_without_wiping_custom_icons(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            data = home / ".local" / "share" / "waybar-shell"
            apps = home / ".local" / "share" / "applications"
            data.mkdir(parents=True)
            apps.mkdir(parents=True)
            (apps / "firefox-esr.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Firefox\n",
                encoding="utf-8",
            )
            icons_path = data / "desktop-icons.json"
            icons_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "icons": [
                            {
                                "id": "custom1",
                                "name": "Notas",
                                "type": "directory",
                                "target": str(home),
                                "icon": "folder",
                                "x": 48,
                                "y": 48,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.dict(
                os.environ,
                {"HOME": str(home), "XDG_DATA_HOME": str(home / ".local" / "share")},
                clear=False,
            ):
                self.assertTrue(
                    seed.ensure_desktop_icons(icons_path, home=home, reset=False, clear=False)
                )
                payload = json.loads(icons_path.read_text(encoding="utf-8"))
                names = [item["name"] for item in payload["icons"]]
                self.assertIn("Notas", names)
                self.assertIn("Firefox", names)
                self.assertFalse(
                    seed.ensure_desktop_icons(icons_path, home=home, reset=False, clear=False)
                )


if __name__ == "__main__":
    unittest.main()
