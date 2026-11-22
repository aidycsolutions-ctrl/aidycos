"""AidyC must not steal AidyChat's dock icon via WM_CLASS prefix matching."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "packaging" / "jugoo-overlay" / "shell"


def _load_icons():
    # icons.py does `from .models import Window` — stub the package.
    pkg = types.ModuleType("shell")
    pkg.__path__ = [str(SHELL)]
    sys.modules["shell"] = pkg
    models = types.ModuleType("shell.models")

    class Window:  # minimal stand-in
        pass

    models.Window = Window
    sys.modules["shell.models"] = models
    spec = importlib.util.spec_from_file_location("shell.icons", SHELL / "icons.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["shell.icons"] = module
    spec.loader.exec_module(module)
    return module


icons = _load_icons()


class WmClassMatchTests(unittest.TestCase):
    def test_prefix_collision_rejected(self) -> None:
        self.assertFalse(icons._wm_class_matches("aidychat", "aidyc"))
        self.assertFalse(icons._wm_class_matches("aidycai", "aidyc"))
        self.assertFalse(icons._wm_class_matches("aidyship", "aidyc"))

    def test_exact_and_separator_ok(self) -> None:
        self.assertTrue(icons._wm_class_matches("aidyc", "aidyc"))
        self.assertTrue(icons._wm_class_matches("org.foo.bar", "bar"))
        self.assertTrue(icons._wm_class_matches("firefox-esr", "firefox"))

    def test_icon_file_is_found_without_the_gtk_theme(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            icon = root / "icons" / "hicolor" / "48x48" / "apps" / "google-chrome.png"
            icon.parent.mkdir(parents=True)
            icon.write_bytes(b"png")
            found = icons.resolve_icon_file("google-chrome", 18, roots=(root,))
            self.assertEqual(found, icon)
            missing = icons.resolve_icon_file("no-such-app", 18, roots=(root,))
            self.assertIsNone(missing)

    def test_resolver_prefers_aidychat(self) -> None:
        resolver = icons.DesktopIconResolver(directories=[])
        resolver._index = {
            "aidyc": icons.ApplicationInfo("AidyC", "aidyc"),
            "aidychat": icons.ApplicationInfo("AidyChat", "aidychat"),
            "aidyship": icons.ApplicationInfo("AidyShip", "aidyship"),
        }
        self.assertEqual(resolver.describe("aidychat").icon, "aidychat")
        self.assertEqual(resolver.describe("aidyc").icon, "aidyc")
        self.assertEqual(resolver.describe("aidyship").icon, "aidyship")


if __name__ == "__main__":
    unittest.main()
