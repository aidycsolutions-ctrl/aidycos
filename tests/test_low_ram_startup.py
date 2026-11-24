"""An 8 GB PC must not map the local model while the session is starting."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "packaging" / "jugoo-overlay"

_BRIEFING = """\
        suffix = f" ({', '.join(details)})" if details else ""

        # Startup briefing: the VRAM gate uses a conservative full-model estimate
        # on an 8\u202fGiB card that often sits a few hundred MiB below the estimate
        # while llama-cli still runs fine. Soft-pass any pure `vram` reject and
        # let the real llama call (timeout / empty / error) decide fallback.
        if viability.reason == "vram":
            free = viability.available_vram_bytes
            est = viability.estimated_vram_bytes
            _briefing_diag(
                "ai_viable: soft-pass vram attempt "
                f"(est={None if est is None else est // (1024 * 1024)} MiB, "
                f"free={None if free is None else free // (1024 * 1024)} MiB)"
            )
            return True, "ok_vram_soft_attempt"

        return False, f"{viability.reason}{suffix}"
"""

_RECURSOS = """\
from pathlib import Path


class AiViability:
    def __init__(self, viable, reason):
        self.viable = viable
        self.reason = reason


def evaluate_ai_viability(
    resources,
    *,
    config,
    model_path: Path | None = None,
):
    path = model_path
    if not path.is_file():
        return AiViability(False, "model_missing")
    if not resources.gpu_memory_reliable:
        return AiViability(True, "ok")
    return AiViability(True, "ok")
"""


def _load_overlay():
    spec = importlib.util.spec_from_file_location(
        "jugoo_overlay_low_ram",
        OVERLAY / "install.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LowRamStartupTests(unittest.TestCase):
    def test_eight_gigabyte_machine_skips_a_large_model(self) -> None:
        overlay = _load_overlay()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            briefing = root / "shell/servicios/tareas/briefing.py"
            recursos = root / "shell/servicios/tareas/vigilancia/recursos.py"
            briefing.parent.mkdir(parents=True)
            recursos.parent.mkdir(parents=True)
            briefing.write_text(_BRIEFING, encoding="utf-8")
            recursos.write_text(_RECURSOS, encoding="utf-8")

            overlay.install_low_ram_startup(root)

            briefing_text = briefing.read_text(encoding="utf-8")
            self.assertNotIn("ok_vram_soft_attempt", briefing_text)
            self.assertIn('return False, f"{viability.reason}{suffix}"', briefing_text)

            spec = importlib.util.spec_from_file_location("patched_recursos", recursos)
            assert spec and spec.loader
            patched = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(patched)

            large = root / "model.gguf"
            with large.open("wb") as stream:
                stream.truncate(600 * 1024 * 1024)
            small = root / "tiny.gguf"
            small.write_bytes(b"x" * 1000)
            eight = 8 * 1024 * 1024 * 1024
            sixteen = 16 * 1024 * 1024 * 1024

            self.assertTrue(patched.machine_cannot_spare_ram_for_model(large, eight))
            self.assertFalse(patched.machine_cannot_spare_ram_for_model(large, sixteen))
            self.assertFalse(patched.machine_cannot_spare_ram_for_model(small, eight))
            self.assertTrue(
                patched.machine_cannot_spare_ram_for_model(root / "missing.gguf", eight)
            )


if __name__ == "__main__":
    unittest.main()
