"""System volume and brightness keys: XF86 media keys and Super+F1…F5."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_medios():
    spec = importlib.util.spec_from_file_location(
        "aidycos_medios",
        ROOT / "packaging" / "hyprland" / "medios.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MediaBindTests(unittest.TestCase):
    def test_block_covers_hardware_keys_and_super_fallback(self) -> None:
        medios = _load_medios()
        block = medios.render_block()
        self.assertIn("XF86AudioMute", block)
        self.assertIn("XF86AudioLowerVolume", block)
        self.assertIn("XF86AudioRaiseVolume", block)
        self.assertIn("XF86MonBrightnessDown", block)
        self.assertIn("XF86MonBrightnessUp", block)
        self.assertIn("bindl = SUPER, F1, exec, ~/.local/bin/aidycos-medios mute", block)
        self.assertIn("bindel = SUPER, F2, exec, ~/.local/bin/aidycos-medios volume-down", block)
        self.assertIn("bindel = SUPER, F3, exec, ~/.local/bin/aidycos-medios volume-up", block)
        self.assertIn("bindel = SUPER, F4, exec, ~/.local/bin/aidycos-medios brightness-down", block)
        self.assertIn("bindel = SUPER, F5, exec, ~/.local/bin/aidycos-medios brightness-up", block)

    def test_ensure_is_idempotent_and_drops_player_volume(self) -> None:
        medios = _load_medios()
        original = (
            "bind = SUPER, SPACE, exec, jugoo action launcher\n"
            "bindel = SUPER, F2, exec, jugoo action musicVolumeDown\n"
            "bindel = SUPER, F3, exec, jugoo action musicVolumeUp\n"
            "bindl = SUPER, F1, exec, jugoo action musicMuteToggle\n"
            "bindl = SUPER, F10, exec, jugoo action playStopMusic\n"
        )
        once = medios.ensure_media_binds(original)
        self.assertNotIn("musicVolumeDown", once)
        self.assertNotIn("musicMuteToggle", once)
        self.assertIn("playStopMusic", once)
        self.assertEqual(once.count(medios.MARKER_BEGIN), 1)
        twice = medios.ensure_media_binds(once)
        self.assertEqual(once, twice)

    def test_apply_script_is_wired(self) -> None:
        text = (ROOT / "scripts" / "install-debian-profile.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/apply-hypr-medios.py", text)
        script = ROOT / "packaging" / "hyprland" / "aidycos-medios"
        body = script.read_text(encoding="utf-8")
        self.assertIn("volume-up", body)
        self.assertIn("brightness-down", body)

    def test_apply_writes_user_config(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "apply_hypr_medios",
            ROOT / "scripts" / "apply-hypr-medios.py",
        )
        assert spec and spec.loader
        apply_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(apply_mod)
        with tempfile.TemporaryDirectory() as temp:
            hypr = Path(temp)
            (hypr / "hyprland.conf").write_text(
                "bindel = SUPER, F3, exec, jugoo action musicVolumeUp\n",
                encoding="utf-8",
            )
            saved = apply_mod.os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
            try:
                code = apply_mod.main(["apply-hypr-medios.py", str(hypr)])
            finally:
                if saved is not None:
                    apply_mod.os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = saved
            self.assertEqual(code, 0)
            conf = (hypr / "aidycos.conf").read_text(encoding="utf-8")
            self.assertIn("XF86AudioRaiseVolume", conf)
            self.assertIn("SUPER, F5", conf)
            landed = (hypr / "hyprland.conf").read_text(encoding="utf-8")
            self.assertNotIn("musicVolumeUp", landed)


if __name__ == "__main__":
    unittest.main()
