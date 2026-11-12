"""CSD title-button heuristics for hyprbars."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "packaging" / "hyprland" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("aidycos_decoraciones", _SCRIPTS / "decoraciones.py")
decoraciones = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(decoraciones)


class DecoracionesTests(unittest.TestCase):
    def test_known_csd_classes(self) -> None:
        self.assertTrue(decoraciones.client_draws_title_buttons(class_name="firefox-esr"))
        self.assertTrue(decoraciones.client_draws_title_buttons(class_name="google-chrome"))
        self.assertTrue(
            decoraciones.client_draws_title_buttons(
                class_name="chrome-hnpfjngllnobngcgfapefoaidbinmjnm-Default"
            )
        )
        self.assertTrue(decoraciones.client_draws_title_buttons(class_name="gnome-disks"))
        self.assertTrue(decoraciones.client_draws_title_buttons(class_name="cursor"))

    def test_non_csd_keeps_hyprbars(self) -> None:
        self.assertFalse(decoraciones.client_draws_title_buttons(class_name="foot"))
        self.assertFalse(decoraciones.client_draws_title_buttons(class_name="thunar"))
        self.assertFalse(decoraciones.client_draws_title_buttons(class_name="aidychat"))
        # libadwaita in maps alone must not hide hyprbars (zenity false positive).
        self.assertFalse(
            decoraciones.client_draws_title_buttons(
                class_name="zenity",
                maps="/usr/lib/libadwaita-1.so.0",
            )
        )

    def test_updated_rules_never_hides_aidychat(self) -> None:
        previous = decoraciones.render_csd_rules(["firefox-esr", "aidychat"])
        rendered = decoraciones.updated_rules(previous, ["firefox-esr", "aidychat"])
        self.assertIsNotNone(rendered)
        assert rendered is not None
        classes = decoraciones.classes_in_rules(rendered)
        self.assertEqual(classes, {"firefox-esr"})
        self.assertNotIn("aidychat", classes)

    def test_executable_fallback(self) -> None:
        self.assertTrue(
            decoraciones.client_draws_title_buttons(
                class_name="some-pwa",
                executable="/opt/google/chrome/chrome",
            )
        )

    def test_updated_rules_prunes_stale_false_positives(self) -> None:
        previous = decoraciones.render_csd_rules(["firefox-esr", "zenity", "foot"])
        rendered = decoraciones.updated_rules(previous, ["firefox-esr"])
        self.assertIsNotNone(rendered)
        assert rendered is not None
        classes = decoraciones.classes_in_rules(rendered)
        self.assertEqual(classes, {"firefox-esr"})
        self.assertNotIn("zenity", classes)
        self.assertNotIn("foot", classes)

    def test_updated_rules_keeps_open_executable_detections(self) -> None:
        previous = decoraciones.render_csd_rules(["firefox-esr"])
        rendered = decoraciones.updated_rules(
            previous,
            ["firefox-esr", "chrome-abcdef-Default"],
        )
        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertEqual(
            decoraciones.classes_in_rules(rendered),
            {"firefox-esr", "chrome-abcdef-Default"},
        )


if __name__ == "__main__":
    unittest.main()
