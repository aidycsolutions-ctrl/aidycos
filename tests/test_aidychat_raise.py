"""AidyChat must open when Hyprland reports that no window exists."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging" / "aidylink"))

from aidylink import notify  # noqa: E402


class FocusCommandTests(unittest.TestCase):
    def test_hyprctl_missing_window_is_not_a_raise(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hyprctl"],
            returncode=0,
            stdout="No such window found\n",
            stderr="",
        )
        self.assertFalse(notify._focus_command_found_window(completed))

    def test_hyprctl_ok_is_a_raise(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hyprctl"],
            returncode=0,
            stdout="ok\n",
            stderr="",
        )
        self.assertTrue(notify._focus_command_found_window(completed))

    def test_silent_success_is_a_raise(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["wmctrl"],
            returncode=0,
            stdout="",
            stderr="",
        )
        self.assertTrue(notify._focus_command_found_window(completed))

    def test_raise_via_wm_keeps_going_after_missing_hypr_window(self) -> None:
        missing = subprocess.CompletedProcess(
            args=["hyprctl"],
            returncode=0,
            stdout="No such window found\n",
            stderr="",
        )
        with mock.patch.object(notify.shutil, "which", return_value="/usr/bin/hyprctl"):
            with mock.patch.object(notify.subprocess, "run", return_value=missing) as run:
                self.assertFalse(notify._raise_via_wm())
        self.assertGreaterEqual(run.call_count, 3)


if __name__ == "__main__":
    unittest.main()
