"""Super+Alt+F4 shuts down after Enter, on every AidyCOS machine."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ShutdownBindTests(unittest.TestCase):
    def test_fresh_config_lands_in_aidycos_conf(self) -> None:
        apagar = _load("aidycos_apagar", ROOT / "packaging" / "hyprland" / "apagar.py")
        hyprland, aidycos = apagar.ensure_shutdown("", "bind = SUPER, SPACE, exec, jugoo action launcher\n")
        self.assertEqual(hyprland, "")
        self.assertIn(apagar.SHUTDOWN_BIND, aidycos)
        self.assertIn("name = confirmar-apagar", aidycos)
        self.assertEqual(aidycos.count(apagar.SHUTDOWN_BIND), 1)
        again_h, again_a = apagar.ensure_shutdown(hyprland, aidycos)
        self.assertEqual(again_a, aidycos)
        self.assertEqual(again_h, hyprland)

    def test_existing_hyprland_bind_is_not_duplicated(self) -> None:
        apagar = _load("aidycos_apagar_keep", ROOT / "packaging" / "hyprland" / "apagar.py")
        hyprland = apagar.SHUTDOWN_BIND + "\n" + apagar.RULE_BLOCK
        new_h, new_a = apagar.ensure_shutdown(hyprland, "bind = SUPER, Q, killactive\n")
        self.assertEqual(new_h, hyprland)
        self.assertNotIn("confirmar-apagar", new_a)

    def test_duplicate_bind_fires_once(self) -> None:
        apagar = _load("aidycos_apagar_once", ROOT / "packaging" / "hyprland" / "apagar.py")
        both = apagar.SHUTDOWN_BIND + "\n"
        hyprland, aidycos = apagar.ensure_shutdown(both, both)
        self.assertNotIn(apagar.SHUTDOWN_BIND, hyprland)
        self.assertIn(apagar.SHUTDOWN_BIND, aidycos)

    def test_installer_ships_it_for_every_machine(self) -> None:
        installer = (ROOT / "scripts" / "install-debian-profile.sh").read_text(encoding="utf-8")
        uninstall = (ROOT / "scripts" / "uninstall-debian-profile.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/apply-hypr-apagar.py", installer)
        self.assertIn(apagar_bind(), installer)
        self.assertIn('remove_path "${hypr_dir}/scripts/confirmar-apagar"', uninstall)
        body = (ROOT / "packaging" / "hyprland" / "scripts" / "confirmar-apagar").read_text(
            encoding="utf-8"
        )
        self.assertIn('["systemctl", "poweroff"]', body)
        self.assertIn("Gdk.KEY_Return", body)
        self.assertIn("Gdk.KEY_Escape", body)
        self.assertIn('gi.require_version("Gtk", "3.0")', body)

    def test_apply_writes_a_machine_without_the_shortcut(self) -> None:
        apply_mod = _load(
            "apply_hypr_apagar",
            ROOT / "scripts" / "apply-hypr-apagar.py",
        )
        with tempfile.TemporaryDirectory() as temp:
            hypr = Path(temp)
            (hypr / "aidycos.conf").write_text(
                "bind = ALT, F4, exec, jugoo action session\n",
                encoding="utf-8",
            )
            saved = apply_mod.os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
            try:
                code = apply_mod.main(["apply-hypr-apagar.py", str(hypr)])
            finally:
                if saved is not None:
                    apply_mod.os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = saved
            self.assertEqual(code, 0)
            conf = (hypr / "aidycos.conf").read_text(encoding="utf-8")
            self.assertIn("SUPER ALT, F4", conf)
            self.assertIn("name = confirmar-apagar", conf)
            script = hypr / "scripts" / "confirmar-apagar"
            self.assertTrue(script.is_file())
            self.assertTrue(script.stat().st_mode & 0o111)


def apagar_bind() -> str:
    return "bind = SUPER ALT, F4, exec, ~/.config/hypr/scripts/confirmar-apagar"


if __name__ == "__main__":
    unittest.main()
