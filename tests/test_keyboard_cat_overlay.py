"""Tests for the AidyCOS keyboard-cat overlay (dance + install)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _load_overlay():
    spec = importlib.util.spec_from_file_location(
        "jugoo_overlay_install",
        ROOT / "packaging" / "jugoo-overlay" / "install.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_keyboard_cat_helpers():
    path = (
        ROOT
        / "packaging"
        / "jugoo-overlay"
        / "shell"
        / "widgets"
        / "barra"
        / "keyboard_cat.py"
    )
    # Import helpers without pulling GTK: exec only the pure functions.
    source = path.read_text(encoding="utf-8")
    start = source.index("def pixel_size_for_bar_height")
    end = source.index("class KeyboardCatWidget")
    ns: dict[str, object] = {"KEYBOARD_CAT_VERTICAL_INSET": 0}
    # Provide the max-size constant used by the helper defaults.
    preamble = "_MAX_PIXEL_SIZE = 96\n_DANCE_FLIP_EVERY = 2\n"
    exec(preamble + source[start:end], ns)
    return ns


class KeyboardCatOverlayTests(unittest.TestCase):
    def test_dance_step_alternates_frames_and_mirrors(self) -> None:
        helpers = _load_keyboard_cat_helpers()
        next_dance_step = helpers["next_dance_step"]
        # With flip_every=2: wag two frame-cycles facing right, then flip.
        step, frame, mirrored = next_dance_step(0, 2, flip_every=2)
        self.assertEqual((step, frame, mirrored), (1, 1, False))
        step, frame, mirrored = next_dance_step(step, 2, flip_every=2)
        self.assertEqual((step, frame, mirrored), (2, 0, False))
        step, frame, mirrored = next_dance_step(step, 2, flip_every=2)
        self.assertEqual((step, frame, mirrored), (3, 1, False))
        step, frame, mirrored = next_dance_step(step, 2, flip_every=2)
        self.assertEqual((step, frame, mirrored), (4, 0, True))
        step, frame, mirrored = next_dance_step(step, 2, flip_every=2)
        self.assertEqual((step, frame, mirrored), (5, 1, True))

    def test_pixel_size_tracks_bar(self) -> None:
        helpers = _load_keyboard_cat_helpers()
        pixel_size_for_bar_height = helpers["pixel_size_for_bar_height"]
        self.assertEqual(pixel_size_for_bar_height(55, inset=0, max_size=96), 55)
        self.assertEqual(pixel_size_for_bar_height(120, inset=0, max_size=96), 96)

    def test_overlay_installs_cat_assets_and_widget(self) -> None:
        overlay = _load_overlay()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "shell" / "app.py"
            config = root / "shell" / "config.py"
            style = root / "shell" / "style.css"
            layout = root / "shell" / "settings" / "layout_model.py"
            for path in (app, config, style, layout):
                path.parent.mkdir(parents=True, exist_ok=True)
            app.write_text(
                "from .servicios.tareas.tasks import TasksService\n"
                "from .widgets.barra.pinned_apps import PinnedAppsWidget\n"
                "class Shell:\n"
                "    def __init__(self):\n"
                "        self.media_service = MediaService(self.event_bus)\n"
                "        self.pinned_apps_widget = PinnedAppsWidget(self.event_bus, self)\n"
                "        self.layout.left.add(self.pinned_apps_widget)\n"
                "        self.show_all()\n"
                "    def close(self):\n"
                "        self.event_bus.clear()\n",
                encoding="utf-8",
            )
            config.write_text("BAR_HEIGHT = 40\n", encoding="utf-8")
            style.write_text("/* base */\n", encoding="utf-8")
            layout.write_text(
                'DEFAULT_LAYOUT = (\n'
                '    ModuleSlot("applications_menu", "left", 1),\n'
                '    ModuleSlot("pinned_apps", "left", 2),\n'
                ')\n',
                encoding="utf-8",
            )

            overlay.install_keyboard_cat(root)

            self.assertTrue(
                (root / "shell/widgets/barra/keyboard_cat.py").is_file()
            )
            self.assertTrue(
                (root / "shell/servicios/teclado/actividad.py").is_file()
            )
            self.assertTrue(
                (root / "shell/assets/cat/keyboard/keyboard_standy.svg").is_file()
            )
            self.assertTrue(
                (root / "shell/assets/cat/keyboard/keyboard_frame1.svg").is_file()
            )
            self.assertTrue(
                (root / "shell/assets/cat/keyboard/keyboard_frame2.svg").is_file()
            )
            app_text = app.read_text(encoding="utf-8")
            self.assertIn("KeyboardCatWidget", app_text)
            self.assertIn("KeyboardActivityService", app_text)
            self.assertIn("self.keyboard_cat_widget", app_text)
            self.assertIn("self.keyboard_activity.start()", app_text)
            self.assertIn("KEYBOARD_CAT_VERTICAL_INSET", config.read_text(encoding="utf-8"))
            self.assertIn("keyboard-cat-widget", style.read_text(encoding="utf-8"))
            self.assertIn("keyboard_cat", layout.read_text(encoding="utf-8"))
            # Idempotent on a second pass.
            overlay.install_keyboard_cat(root)
            self.assertEqual(app_text, app.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
