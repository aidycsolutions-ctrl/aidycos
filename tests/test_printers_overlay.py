from __future__ import annotations

import importlib.util
import sys
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


def _load_service():
    service_path = (
        ROOT
        / "packaging"
        / "jugoo-overlay"
        / "shell"
        / "servicios"
        / "impresoras"
        / "service.py"
    )
    spec = importlib.util.spec_from_file_location("aidycos_printers_service", service_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PrintersOverlayTests(unittest.TestCase):
    def test_overlay_installs_printers_category(self) -> None:
        overlay = _load_overlay()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            schema = root / "shell" / "settings" / "schema.py"
            pages = root / "shell" / "widgets" / "configuraciones" / "pages.py"
            pane = root / "shell" / "widgets" / "configuraciones" / "pane.py"
            settings_overlay = root / "shell" / "widgets" / "configuraciones" / "overlay.py"
            style = root / "shell" / "style.css"
            for path in (schema, pages, pane, settings_overlay, style):
                path.parent.mkdir(parents=True, exist_ok=True)

            schema.write_text(
                'class CategoryId(str, Enum):\n'
                '    GENERAL = "general"\n'
                '    ATAJOS = "atajos"\n'
                '    AVANZADO = "avanzado"\n'
                "\n"
                "CATEGORY_META: dict[CategoryId, tuple[str, str]] = {\n"
                '    CategoryId.ATAJOS: ("Atajos", "Atajos de teclado activos (solo lectura)"),\n'
                '    CategoryId.AVANZADO: ("Avanzado", "Rendimiento e integraciones"),\n'
                "}\n",
                encoding="utf-8",
            )
            pages.write_text(
                "from .shortcuts_page import build_shortcuts_page\n"
                "\n"
                "def build_category_page(manager, category, *, on_change):\n"
                "    if category is CategoryId.ATAJOS:\n"
                "        return build_shortcuts_page()\n"
                "    return Gtk.Box()\n",
                encoding="utf-8",
            )
            pane.write_text(
                "def ordered_categories(manager: SettingsManager) -> tuple[CategoryId, ...]:\n"
                '    """Nav order for the live Settings UI (launcher settings mode).\n'
                "\n"
                "    ``CategoryId.ATAJOS`` is catalog-free (no SettingDef) so it never appears in\n"
                "    ``categories_present()``; insert it once before Avanzado for the real menu.\n"
                '    """\n'
                "    ordered = (CategoryId.GENERAL,) + tuple(\n"
                "        category\n"
                "        for category in manager.categories_present()\n"
                "        if category is not CategoryId.GENERAL\n"
                "    )\n"
                "    if CategoryId.ATAJOS in ordered:\n"
                "        return ordered\n"
                "    insert_at = len(ordered)\n"
                "    for index, category in enumerate(ordered):\n"
                "        if category is CategoryId.AVANZADO:\n"
                "            insert_at = index\n"
                "            break\n"
                "    return ordered[:insert_at] + (CategoryId.ATAJOS,) + ordered[insert_at:]\n",
                encoding="utf-8",
            )
            settings_overlay.write_text(
                "        ordered = (CategoryId.GENERAL,)\n"
                "        # Atajos is catalog-free (read-only registry page); always offer it.\n"
                "        if CategoryId.ATAJOS not in ordered:\n"
                "            insert_at = len(ordered)\n"
                "            for index, cat in enumerate(ordered):\n"
                "                if cat is CategoryId.AVANZADO:\n"
                "                    insert_at = index\n"
                "                    break\n"
                "            ordered = ordered[:insert_at] + (CategoryId.ATAJOS,) + ordered[insert_at:]\n"
                "        for category in ordered:\n"
                "            pass\n",
                encoding="utf-8",
            )
            style.write_text("/* base */\n", encoding="utf-8")

            overlay.install_printers(root)

            self.assertTrue(
                (root / "shell/servicios/impresoras/service.py").is_file()
            )
            self.assertTrue(
                (root / "shell/widgets/configuraciones/printers_page.py").is_file()
            )
            schema_text = schema.read_text(encoding="utf-8")
            self.assertIn('IMPRESORAS = "impresoras"', schema_text)
            self.assertIn('"Impresoras"', schema_text)
            pages_text = pages.read_text(encoding="utf-8")
            self.assertIn("build_printers_page", pages_text)
            self.assertIn("CategoryId.IMPRESORAS", pages_text)
            self.assertIn("IMPRESORAS", pane.read_text(encoding="utf-8"))
            self.assertIn("IMPRESORAS", settings_overlay.read_text(encoding="utf-8"))
            self.assertIn("settings-printer-row", style.read_text(encoding="utf-8"))

    def test_service_parses_spanish_lpstat(self) -> None:
        service = _load_service()
        calls = {
            ("lpstat", "-d"): "destino predeterminado del sistema: HP_Smart_Tank_WiFi\n",
            ("lpstat", "-a"): (
                "HP_Smart_Tank_585 aceptando peticiones desde mié 04 nov 2026 22:58:27\n"
                "HP_Smart_Tank_WiFi aceptando peticiones desde mié 04 nov 2026 23:05:19\n"
            ),
            ("lpstat", "-p"): (
                "la impresora HP_Smart_Tank_585 está inactiva.  activada desde mié 04 nov 2026 22:58:27\n"
                "la impresora HP_Smart_Tank_WiFi está inactiva.  desactivada desde mié 04 nov 2026 23:05:19\n"
            ),
            ("lpstat", "-v"): (
                "device for HP_Smart_Tank_585: hp:/usb/Smart_Tank\n"
                "device for HP_Smart_Tank_WiFi: ipp://192.168.1.10/ipp/print\n"
            ),
        }

        def fake_run(argv, **_kwargs):
            key = tuple(argv)
            class Result:
                returncode = 0
                stdout = calls[key]
                stderr = ""

            return Result()

        original_run = service.subprocess.run
        original_which = service.shutil.which
        service.subprocess.run = fake_run
        service.shutil.which = lambda _name: "/usr/bin/lpstat"
        try:
            snapshot = service.list_printers()
        finally:
            service.subprocess.run = original_run
            service.shutil.which = original_which

        self.assertIsNone(snapshot.error)
        self.assertEqual(snapshot.default_name, "HP_Smart_Tank_WiFi")
        by_name = {item.name: item for item in snapshot.printers}
        self.assertTrue(by_name["HP_Smart_Tank_585"].enabled)
        self.assertFalse(by_name["HP_Smart_Tank_WiFi"].enabled)
        self.assertTrue(by_name["HP_Smart_Tank_WiFi"].is_default)
        self.assertIn("ipp://", by_name["HP_Smart_Tank_WiFi"].device_uri)


if __name__ == "__main__":
    unittest.main()
