"""Unit tests for AidyShip git helpers (no GTK, no network)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging" / "aidyship"
sys.path.insert(0, str(PACKAGING))

from aidyship.config import ShipConfig, add_favorite, load_config, save_config  # noqa: E402
from aidyship.gitops import find_git_root, repo_status  # noqa: E402
from aidyship.paths import config_path  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


class AidyshipGitopsTest(unittest.TestCase):
    def test_status_lists_untracked_and_modified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "demo"
            repo.mkdir()
            _git(repo, "init")
            _git(repo, "config", "user.email", "aidyship@test.local")
            _git(repo, "config", "user.name", "AidyShip Test")
            (repo / "a.txt").write_text("one\n", encoding="utf-8")
            _git(repo, "add", "a.txt")
            _git(repo, "commit", "-m", "init")
            (repo / "a.txt").write_text("two\n", encoding="utf-8")
            (repo / "b.txt").write_text("new\n", encoding="utf-8")

            status = repo_status(repo)
            self.assertTrue(status.ok)
            self.assertEqual(status.root, repo.resolve())
            paths = {item.path for item in status.files}
            self.assertIn("a.txt", paths)
            self.assertIn("b.txt", paths)

            nested = find_git_root(repo / "b.txt")
            self.assertEqual(nested, repo.resolve())

    def test_favorites_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_home = Path(tmp) / "config"
            cfg_home.mkdir()
            import os

            os.environ["XDG_CONFIG_HOME"] = str(cfg_home)
            # Reload path helper after env change by calling config_path.
            self.assertTrue(str(config_path()).startswith(str(cfg_home)))
            cfg = ShipConfig()
            cfg = add_favorite(cfg, Path(tmp) / "repo-a")
            cfg = add_favorite(cfg, Path(tmp) / "repo-b")
            again = load_config()
            self.assertEqual(again.favorites[0], str((Path(tmp) / "repo-b").resolve()))
            self.assertEqual(len(again.favorites), 2)
            save_config(again)


if __name__ == "__main__":
    unittest.main()
