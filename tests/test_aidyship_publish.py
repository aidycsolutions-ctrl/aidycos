"""Tests for AidyShip deploy profile detection (no SSH)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging" / "aidyship"))

from aidyship.publish import detect_deploy_profile  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


class AidyshipPublishTest(unittest.TestCase):
    def test_detects_aidyc_web_by_folder_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "AidyC-web"
            repo.mkdir()
            _git(repo, "init")
            _git(repo, "remote", "add", "origin", "https://github.com/aidycsolutions-ctrl/AidyC-web.git")
            profile = detect_deploy_profile(repo)
            self.assertIsNotNone(profile)
            assert profile is not None
            self.assertTrue(profile.can_deploy)
            self.assertEqual(profile.deploy_host, "ssh.pythonanywhere.com")
            self.assertEqual(profile.branch, "main")

    def test_other_repos_have_no_deploy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "other-app"
            repo.mkdir()
            _git(repo, "init")
            self.assertIsNone(detect_deploy_profile(repo))


if __name__ == "__main__":
    unittest.main()
