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


if __name__ == "__main__":
    unittest.main()
