#!/usr/bin/env python3
"""Install Super+Alt+F4 (Enter confirma el apagado) into the Hyprland session.

  python3 scripts/apply-hypr-apagar.py
  python3 scripts/apply-hypr-apagar.py ~/.config/hypr
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _load_apagar():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "packaging" / "hyprland"))
    import apagar  # noqa: WPS433

    return apagar


def main(argv: list[str]) -> int:
    apagar = _load_apagar()
    root = Path(__file__).resolve().parents[1]
    hypr_dir = Path(argv[1]).expanduser() if len(argv) > 1 else Path.home() / ".config" / "hypr"
    hypr_dir.mkdir(parents=True, exist_ok=True)
    scripts = hypr_dir / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)

    src = root / "packaging" / "hyprland" / "scripts" / "confirmar-apagar"
    dst = scripts / "confirmar-apagar"
    shutil.copyfile(src, dst)
    dst.chmod(0o755)

    hyprland_path = hypr_dir / "hyprland.conf"
    aidycos_path = hypr_dir / "aidycos.conf"
    hyprland = hyprland_path.read_text(encoding="utf-8") if hyprland_path.is_file() else ""
    aidycos = aidycos_path.read_text(encoding="utf-8") if aidycos_path.is_file() else ""
    new_hyprland, new_aidycos = apagar.ensure_shutdown(hyprland, aidycos)
    if hyprland_path.is_file() and new_hyprland != hyprland:
        hyprland_path.write_text(new_hyprland, encoding="utf-8")
    if new_aidycos != aidycos:
        aidycos_path.write_text(new_aidycos, encoding="utf-8")

    print(f"ok apagar={dst}")
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        try:
            subprocess.run(["hyprctl", "reload"], check=False, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
