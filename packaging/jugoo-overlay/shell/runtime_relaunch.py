"""Relaunch the Jugoo shell process without racing the old layer-shell surface."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def relaunch_argv() -> list[str]:
    """Build argv for replacing this process with a fresh Jugoo instance."""
    jugoo = shutil.which("jugoo")
    if jugoo:
        return [jugoo]
    return [sys.executable, "-m", "shell", *sys.argv[1:]]


def relaunch_shell() -> None:
    """Spawn a delayed Jugoo and exit this process.

    A bare ``os.execv`` keeps the same PID and swaps the image while Hyprland
    still holds the previous GtkLayerShell exclusive zone. On cold login that
    race never happens. On ``Reiniciar Jugoo`` (especially Yurle's 2.5 GB
    machine) the new bar paints with missing fonts/icons — orange tofu for
    ⏮/⏭ and blank workspace icons. Detach, wait, then start clean.
    """
    argv = relaunch_argv()
    subprocess.Popen(
        ["bash", "-c", 'sleep 0.45; exec "$@"', "jugoo-relaunch", *argv],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    # Hard exit so the Wayland connection drops before the child starts.
    os._exit(0)
