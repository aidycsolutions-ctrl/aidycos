from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPLY = ROOT / "packaging" / "boot" / "apply-aidycos-boot.sh"
GFXMODE = ROOT / "packaging" / "boot" / "aidycos-boot-gfxmode"
GRUB_BG = ROOT / "packaging" / "boot" / "aidycos-grub-background"
LOGO = ROOT / "packaging" / "plymouth" / "AidyCOS.png"
INSTALLER = ROOT / "scripts" / "install-debian-profile.sh"


class BootSplashTests(unittest.TestCase):
    def test_installer_calls_boot_splash_helper(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("packaging/boot/apply-aidycos-boot.sh", text)
        self.assertNotIn("command -v update-grub", text)

    def test_apply_script_uses_absolute_sbin_fallbacks(self) -> None:
        text = APPLY.read_text(encoding="utf-8")
        self.assertIn('/usr/sbin/${name}', text)
        self.assertIn("zz-aidycos.cfg", text)
        self.assertIn("aidyc.cfg", text)
        self.assertIn("Theme=aidycos", text)
        self.assertIn("FRAMEBUFFER=y", text)
        self.assertTrue(APPLY.stat().st_mode & stat.S_IXUSR)

    def test_find_sbin_works_without_usr_sbin_in_path(self) -> None:
        text = APPLY.read_text(encoding="utf-8")
        start = text.index("find_sbin() {")
        end = text.index("\n}\n", start) + 3
        helper = text[start:end]
        probe = f"""#!/usr/bin/env bash
set -euo pipefail
{helper}
PATH=/usr/bin:/bin
found="$(find_sbin update-grub)"
test -x "${{found}}"
printf '%s\\n' "${{found}}"
"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "probe.sh"
            path.write_text(probe, encoding="utf-8")
            path.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = "/usr/bin:/bin"
            result = subprocess.run(
                ["bash", str(path)],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        self.assertTrue(result.stdout.strip().endswith("update-grub"))
        self.assertTrue(Path(result.stdout.strip()).is_file())

    def test_gfxmode_helper_prints_auto_fallback(self) -> None:
        result = subprocess.run(
            ["python3", str(GFXMODE)],
            check=True,
            capture_output=True,
            text=True,
        )
        line = result.stdout.strip()
        self.assertTrue(line.endswith(",auto"))
        self.assertIn("1920x1080", line)

    def test_grub_background_keeps_logo_aspect_on_widescreen(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "grub.png"
            subprocess.run(
                [
                    "python3",
                    str(GRUB_BG),
                    "--logo",
                    str(LOGO),
                    "--size",
                    "1920x1080",
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            image = Image.open(output).convert("RGB")
            self.assertEqual(image.size, (1920, 1080))
            # Corners stay pure black; a stretched square logo would tint them.
            for point in ((0, 0), (1919, 0), (0, 1079), (1919, 1079)):
                self.assertEqual(image.getpixel(point), (0, 0, 0))
            # Mid row should include logo color, not only black letterboxing.
            mid = [image.getpixel((x, 540)) for x in range(0, 1920, 20)]
            self.assertTrue(any(max(pixel) > 20 for pixel in mid))
            self.assertIn("aidycos-grub-background", APPLY.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
