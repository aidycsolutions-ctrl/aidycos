"""KP_Enter is delivered as Return without dropping the current layout."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_keymap():
    spec = importlib.util.spec_from_file_location(
        "aidycos_keymap",
        ROOT / "packaging" / "hyprland" / "keymap.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KeymapTests(unittest.TestCase):
    def test_keymap_keeps_layout_and_remaps_keypad_enter(self) -> None:
        keymap = _load_keymap()
        text = keymap.render_keymap("latam")
        self.assertIn('include "pc+latam+inet(evdev)"', text)
        self.assertIn("key <KPEN> { [ Return ] };", text)

    def test_variant_is_included(self) -> None:
        keymap = _load_keymap()
        self.assertEqual(keymap.symbols_include("us", "intl"), "us(intl)")
        self.assertEqual(keymap.symbols_include("latam,us", ""), "latam")

    def test_apply_inserts_kb_file_once(self) -> None:
        keymap = _load_keymap()
        with tempfile.TemporaryDirectory() as temp:
            hypr = Path(temp)
            (hypr / "hyprland.conf").write_text(
                "input {\n    kb_layout = us\n    kb_variant = intl\n}\n",
                encoding="utf-8",
            )
            (hypr / "aidycos.conf").write_text(
                "input {\n    numlock_by_default = true\n}\n",
                encoding="utf-8",
            )
            keymap_path, changed = keymap.apply_to_config_dir(hypr)
            self.assertEqual(keymap_path.name, "aidycos-keymap.xkb")
            body = keymap_path.read_text(encoding="utf-8")
            self.assertIn('include "pc+us(intl)+inet(evdev)"', body)
            self.assertEqual(len(changed), 2)
            again_path, again_changed = keymap.apply_to_config_dir(hypr)
            self.assertEqual(again_changed, [])
            conf = (hypr / "hyprland.conf").read_text(encoding="utf-8")
            self.assertEqual(conf.count("kb_file ="), 1)
            self.assertIn("kb_file = ~/.config/hypr/aidycos-keymap.xkb", conf)
            self.assertTrue(again_path.is_file())

    def test_custom_kb_file_is_kept(self) -> None:
        keymap = _load_keymap()
        original = "input {\n    kb_file = ~/my.map\n}\n"
        self.assertEqual(keymap.ensure_kb_file(original), original)

    def test_installer_applies_keymap_and_raw_queue(self) -> None:
        text = (ROOT / "scripts" / "install-debian-profile.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/apply-hypr-keymap.py", text)
        self.assertIn("scripts/apply-escpos-printer.py", text)
        self.assertIn("kb_file = ~/.config/hypr/aidycos-keymap.xkb", text)


if __name__ == "__main__":
    unittest.main()
