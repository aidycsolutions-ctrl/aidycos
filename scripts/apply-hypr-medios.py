#!/usr/bin/env python3
"""Install system volume and brightness keys into the Hyprland session.

  python3 scripts/apply-hypr-medios.py
  python3 scripts/apply-hypr-medios.py ~/.config/hypr
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _load_medios():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "packaging" / "hyprland"))
    import medios  # noqa: WPS433

    return medios


def main(argv: list[str]) -> int:
    medios = _load_medios()
    root = Path(__file__).resolve().parents[1]
    hypr_dir = Path(argv[1]).expanduser() if len(argv) > 1 else Path.home() / ".config" / "hypr"
    hypr_dir.mkdir(parents=True, exist_ok=True)

    bin_dir = Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script_src = root / "packaging" / "hyprland" / "aidycos-medios"
    script_dst = bin_dir / "aidycos-medios"
    shutil.copyfile(script_src, script_dst)
    script_dst.chmod(0o755)

    aidycos = hypr_dir / "aidycos.conf"
    original = aidycos.read_text(encoding="utf-8") if aidycos.is_file() else ""
    updated = medios.ensure_media_binds(original)
    if updated != original:
        aidycos.write_text(updated, encoding="utf-8")

    hyprland = hypr_dir / "hyprland.conf"
    if hyprland.is_file():
        conf = hyprland.read_text(encoding="utf-8")
        stripped = medios.retire_player_volume_binds(conf)
        if stripped != conf:
            hyprland.write_text(stripped, encoding="utf-8")

    print(f"ok medios={script_dst} conf={aidycos}")
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        try:
            subprocess.run(["hyprctl", "reload"], check=False, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
