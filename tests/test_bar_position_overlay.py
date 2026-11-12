from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


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


class BarPositionOverlayTests(unittest.TestCase):
    def test_overlay_installs_barra_position_setting(self) -> None:
        overlay = _load_overlay()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "shell" / "config.py"
            schema = root / "shell" / "settings" / "schema.py"
            identity = root / "shell" / "window_identity.py"
            app = root / "shell" / "app.py"
            layout = root / "shell" / "layout.py"
            style = root / "shell" / "style.css"
            for path in (config, schema, identity, app, layout, style):
                path.parent.mkdir(parents=True, exist_ok=True)

            config.write_text(
                "# Layer-shell top inset. 0 anchors the bar flush with the monitor edge (y=0).\n"
                "TOP_MARGIN = 0\n",
                encoding="utf-8",
            )
            schema.write_text(
                "from .. import config as shell_config\n"
                "\n"
                "def build_settings_catalog():\n"
                "    return (\n"
                "        SettingDef(\n"
                '            key="barra.top_margin",\n'
                '            label="Margen superior",\n'
                '            description="Inset de la barra respecto al borde del monitor.",\n'
                "        ),\n"
                "    )\n"
                "\n"
                "\n"
                "def settings_by_key():\n"
                "    return {}\n",
                encoding="utf-8",
            )
            identity.write_text(
                "def compute_popup_top_left(*, button_center_x, button_bottom, popup_width, "
                "popup_height, offset, fixed_top=None, monitor=None, margin=None):\n"
                '    """Top-left popup coordinates: centered on the anchor, top below the button."""\n'
                "    edge = shell_config.POPUP_EDGE_MARGIN if margin is None else margin\n"
                "    popup_left = button_center_x - popup_width // 2\n"
                "    popup_top = fixed_top if fixed_top is not None else button_bottom + offset\n"
                "\n"
                "    if monitor is not None:\n"
                "        mon_left = monitor.x\n"
                "        mon_top = monitor.y\n"
                "        mon_right = monitor.x + monitor.width\n"
                "        mon_bottom = monitor.y + monitor.height\n"
                "\n"
                "        popup_left = max(\n"
                "            mon_left + edge,\n"
                "            min(popup_left, mon_right - popup_width - edge),\n"
                "        )\n"
                "        # Never slide the window up to fit a taller size: that overlaps the bar.\n"
                "        # Popups grow downward; content that does not fit scrolls.\n"
                "        popup_top = max(mon_top + edge, popup_top)\n"
                "\n"
                "    return int(popup_left), int(popup_top)\n"
                "\n"
                "\n"
                "def position_popup_below_anchor(window, anchor, *, title, offset, "
                "fixed_top=None, margin=None, extra_y_offset=0):\n"
                '    """Position a popup from anchor geometry and popup size; return the top edge used."""\n'
                "    geometry = anchor_button_geometry(anchor)\n"
                "    if geometry is None:\n"
                "        return None\n"
                "\n"
                "    popup_width, popup_height = popup_window_size(window)\n"
                "    monitor = monitor_containing_point(geometry.center_x, geometry.bottom)\n"
                "    popup_left, popup_top = compute_popup_top_left(\n"
                "        button_center_x=geometry.center_x,\n"
                "        button_bottom=geometry.bottom,\n"
                "        popup_width=popup_width,\n"
                "        popup_height=popup_height,\n"
                "        offset=offset + extra_y_offset,\n"
                "        fixed_top=(fixed_top + extra_y_offset) if fixed_top is not None else None,\n"
                "        monitor=monitor,\n"
                "        margin=margin,\n"
                "    )\n"
                "    reposition_popup(window, title=title, x=popup_left, y=popup_top)\n"
                "    return popup_top\n",
                encoding="utf-8",
            )
            app.write_text(
                "from .config import (\n"
                "    ACTIVE_THEME,\n"
                "    HYPRLAND_THEME_EXPORT_PATH,\n"
                "    PERSISTENT_WORKSPACES,\n"
                "    TOP_MARGIN,\n"
                ")\n"
                "\n"
                "class ShellApplication:\n"
                "    def _configure_layer_shell(self) -> None:\n"
                "        GtkLayerShell.init_for_window(self)\n"
                "        GtkLayerShell.set_namespace(self, APP_ID)\n"
                "        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)\n"
                "        for edge in (\n"
                "            GtkLayerShell.Edge.TOP,\n"
                "            GtkLayerShell.Edge.LEFT,\n"
                "            GtkLayerShell.Edge.RIGHT,\n"
                "        ):\n"
                "            GtkLayerShell.set_anchor(self, edge, True)\n"
                "        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, TOP_MARGIN)\n"
                "        GtkLayerShell.auto_exclusive_zone_enable(self)\n"
                "        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)\n"
                "        monitor = _gdk_monitor()\n"
                "        if monitor is not None:\n"
                "            GtkLayerShell.set_monitor(self, monitor)\n"
                "\n"
                "    def __init__(self):\n"
                "        self.layout = ShellLayout()\n"
                "        monitor = _gdk_monitor()\n"
                "        if monitor is not None:\n"
                "            self.layout.set_size_request(monitor.get_geometry().width, -1)\n"
                "\n"
                "        # Starfield paints the void; layout modules sit as its child above the stars.\n"
                "        self._bar_host = StarfieldBackground(\n"
                "            self.event_bus,\n"
                "            corner_radius=0.0,\n"
                "            draw_rim=True,\n"
                "        )\n"
                "        self._bar_host.get_style_context().add_class(\"shell-bar-host\")\n"
                "        self._bar_host.set_hexpand(True)\n"
                "        self._bar_host.set_halign(Gtk.Align.FILL)\n"
                "        self._bar_host.add(self.layout)\n"
                "\n"
                "        self._overlay = Gtk.Overlay()\n"
                "        self._overlay.set_hexpand(True)\n"
                "        self._overlay.set_halign(Gtk.Align.FILL)\n"
                "        if monitor is not None:\n"
                "            self._overlay.set_size_request(monitor.get_geometry().width, -1)\n"
                "        self._overlay.add(self._bar_host)\n"
                "        self.add(self._overlay)\n"
                "        if monitor is not None:\n"
                "            self.set_size_request(monitor.get_geometry().width, -1)\n",
                encoding="utf-8",
            )
            layout.write_text("class ShellLayout: ...\n", encoding="utf-8")
            style.write_text("box.shell-bar { padding: 0; }\n", encoding="utf-8")

            overlay.install_bar_position(root)

            self.assertIn('BAR_POSITION = "top"', config.read_text(encoding="utf-8"))
            schema_text = schema.read_text(encoding="utf-8")
            self.assertIn('key="barra.position"', schema_text)
            self.assertIn('("bottom", "Abajo")', schema_text)
            self.assertIn("Margen del borde", schema_text)
            self.assertIn("configure_bar_layer_shell", app.read_text(encoding="utf-8"))
            self.assertIn("compute_popup_for_bar", identity.read_text(encoding="utf-8"))
            self.assertIn("shell-bar-vertical", style.read_text(encoding="utf-8"))
            self.assertTrue((root / "shell" / "bar_position.py").is_file())
            self.assertIn("is_vertical_bar", (root / "shell" / "layout.py").read_text(encoding="utf-8"))

            # Idempotent second pass.
            overlay.install_bar_position(root)
            self.assertEqual(1, schema.read_text(encoding="utf-8").count('key="barra.position"'))


if __name__ == "__main__":
    unittest.main()
