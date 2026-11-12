"""Load Jugoo with AidyCOS icon overrides without rewriting /opt."""
from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path

JUGOO_DIR = Path("/opt/aidyc/jugoo")
if (Path.home() / ".local/share/aidycos/jugoo/shell").is_dir() and not (JUGOO_DIR / ".aidycos-managed").is_file():
    JUGOO_DIR = Path.home() / ".local/share/aidycos/jugoo"

PATCH = Path.home() / ".local/share/aidycos/patches/icons.py"

sys.path.insert(0, str(JUGOO_DIR))


def _apply_icons_patch() -> None:
    if not PATCH.is_file():
        return
    import shell.icons as target

    spec = importlib.util.spec_from_file_location("_aidycos_icons_patch", PATCH)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "shell"
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    target.application_for_window = module.application_for_window
    target.icon_for_window = module.icon_for_window
    target.find_desktop_icon = module.find_desktop_icon
    target._resolver = module._resolver


try:
    _apply_icons_patch()
except Exception as error:  # noqa: BLE001
    print(f"aidycos: icon patch skipped: {error}", flush=True)

runpy.run_module("shell", run_name="__main__")
