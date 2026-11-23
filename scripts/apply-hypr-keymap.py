#!/usr/bin/env python3
"""Make keypad Intro (KP_Enter) act as Enter in the Hyprland session.

  python3 scripts/apply-hypr-keymap.py
  python3 scripts/apply-hypr-keymap.py ~/.config/hypr
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _load_keymap():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "packaging" / "hyprland"))
    import keymap  # noqa: WPS433

    return keymap


def main(argv: list[str]) -> int:
    keymap = _load_keymap()
    hypr_dir = Path(argv[1]).expanduser() if len(argv) > 1 else Path.home() / ".config" / "hypr"
    keymap_path, changed = keymap.apply_to_config_dir(hypr_dir)
    names = ",".join(path.name for path in changed) if changed else "-"
    print(f"ok keymap={keymap_path} actualizados={names}")
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        try:
            subprocess.run(["hyprctl", "reload"], check=False, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
