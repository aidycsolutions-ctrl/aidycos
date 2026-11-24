"""CPU and RAM leave the bar and ride on the fan tooltip."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATS = (
    ROOT
    / "packaging"
    / "jugoo-overlay"
    / "shell"
    / "widgets"
    / "barra"
    / "stats.py"
)


def _load_overlay():
    spec = importlib.util.spec_from_file_location(
        "jugoo_overlay_install",
        ROOT / "packaging" / "jugoo-overlay" / "install.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StatsFanOverlayTests(unittest.TestCase):
    def test_fan_tooltip_carries_cpu_and_ram(self) -> None:
        text = STATS.read_text(encoding="utf-8")
        self.assertIn("def system_stats_tooltip", text)
        self.assertIn("CPU:", text)
        self.assertIn("RAM:", text)
        self.assertNotIn("self.pack_start(self._build_cpu_section()", text)
        self.assertNotIn("self.pack_start(self._build_memory_section()", text)
        self.assertIn("self.pack_start(self._build_gpu_section()", text)
        self.assertIn("system_stats_tooltip(stats)", text)

    def test_install_replaces_stock_stats_widget(self) -> None:
        overlay = _load_overlay()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            destination = root / "shell" / "widgets" / "barra" / "stats.py"
            destination.parent.mkdir(parents=True)
            destination.write_text(
                "self.pack_start(self._build_cpu_section(), False, False, 0)\n",
                encoding="utf-8",
            )
            overlay.install_stats_fan_tooltip(root)
            installed = destination.read_text(encoding="utf-8")
            self.assertEqual(installed, STATS.read_text(encoding="utf-8"))
            self.assertNotIn("self.pack_start(self._build_cpu_section()", installed)


if __name__ == "__main__":
    unittest.main()
