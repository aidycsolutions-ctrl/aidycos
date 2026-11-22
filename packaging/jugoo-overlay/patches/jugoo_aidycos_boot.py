"""Load Jugoo with AidyCOS patches without rewriting /opt when possible."""
from __future__ import annotations

import importlib
import importlib.util
import runpy
import sys
from pathlib import Path

OPT_JUGOO = Path("/opt/aidyc/jugoo")
USER_JUGOO = Path.home() / ".local/share/aidycos/jugoo"

# Prefer the user checkout when it carries newer AidyCOS bar modules that
# have not been deployed to /opt yet (no sudo). Otherwise use managed /opt.
if (USER_JUGOO / "shell/widgets/barra/host_identity.py").is_file():
    JUGOO_DIR = USER_JUGOO
elif (OPT_JUGOO / ".aidycos-managed").is_file() and (OPT_JUGOO / "shell").is_dir():
    JUGOO_DIR = OPT_JUGOO
elif (USER_JUGOO / "shell").is_dir():
    JUGOO_DIR = USER_JUGOO
else:
    JUGOO_DIR = OPT_JUGOO

PATCHES = Path.home() / ".local/share/aidycos/patches"
ICONS_PATCH = PATCHES / "icons.py"

# Drop a stale PYTHONPATH pointing at /opt so user overlay modules win.
sys.path = [p for p in sys.path if Path(p).resolve() != OPT_JUGOO.resolve()]
sys.path.insert(0, str(JUGOO_DIR))


def _load_patch_module(module_name: str, path: Path, *, package: str) -> None:
    """Register ``path`` as ``module_name`` before Jugoo imports the stock file."""
    if not path.is_file():
        return
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    module.__package__ = package
    module.__file__ = str(path)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)


def _apply_icons_patch() -> None:
    if not ICONS_PATCH.is_file():
        return
    import shell.icons as target

    spec = importlib.util.spec_from_file_location("_aidycos_icons_patch", ICONS_PATCH)
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


def _apply_session_menu_patches() -> None:
    """Cancel/Esc session menu + short Alt+F4 grace (user-writable patches)."""
    import shell  # noqa: F401 — package must exist for relative imports

    _load_patch_module(
        "shell.popup_handle",
        PATCHES / "popup_handle.py",
        package="shell",
    )
    importlib.import_module("shell.widgets.barra")
    _load_patch_module(
        "shell.widgets.barra.power",
        PATCHES / "power.py",
        package="shell.widgets.barra",
    )


def _apply_workspace_strip_defaults() -> None:
    """Live Hyprland list only — no reserved empty desktop dots 1–5."""
    try:
        import shell.config as config

        config.PERSISTENT_WORKSPACES = None
    except Exception as error:  # noqa: BLE001
        print(f"aidycos: workspace strip defaults skipped: {error}", flush=True)


try:
    _apply_icons_patch()
except Exception as error:  # noqa: BLE001
    print(f"aidycos: icon patch skipped: {error}", flush=True)

try:
    _apply_session_menu_patches()
except Exception as error:  # noqa: BLE001
    print(f"aidycos: session menu patch skipped: {error}", flush=True)

_apply_workspace_strip_defaults()

runpy.run_module("shell", run_name="__main__")
