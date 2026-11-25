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
    target.resolve_icon_file = module.resolve_icon_file
    target.configure_workspace_icon = module.configure_workspace_icon
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


def _apply_workspace_icon_files() -> None:
    """Draw the center workspace-pill program icons from files.

    That center pill is what should show Chrome/Cursor/OnlyOffice. After
    ``Reiniciar Jugoo`` on Yurle, GTK theme lookup often returns empty and the
    pill looks blank (or like empty orange slots). Painting the PNG/SVG from
    disk keeps those program icons visible.
    """
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    import shell.icons as icons
    import shell.widgets.barra.workspace as workspace

    paint = icons.configure_workspace_icon
    original = workspace.WorkspaceApplicationIcon.__init__

    def __init__(self, window, icon_name: str, focused: bool) -> None:
        original(self, window, icon_name, focused)
        image = self.get_child()
        if not isinstance(image, Gtk.Image):
            return
        size = image.get_pixel_size() or 18

        def repaint(*_args: object) -> bool:
            paint(image, icon_name, size)
            return False

        repaint()
        self.connect("realize", repaint)
        self.connect("map", repaint)
        # Yurle: theme/cache can lag past the first realize after a restart.
        GLib.timeout_add(200, repaint)
        GLib.timeout_add(800, repaint)
        GLib.timeout_add(2000, repaint)

    workspace.WorkspaceApplicationIcon.__init__ = __init__


def _apply_active_window_icons() -> None:
    """Avoid emoji tofu and blank app icons in the left active-window block.

    After ``Reiniciar Jugoo`` on Yurle the color-emoji font is not ready yet, so
    ⏮/⏭ paint as orange squares with a lone ▶ between them — the bar looks
    “broken”. Prefer on-disk Tango action PNGs (not only -symbolic names).
    """
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    import shell.icons as icons
    import shell.widgets.barra.active_window as active_window

    paint = icons.configure_workspace_icon
    # Prefer names that resolve to real PNG/SVG files under actions/, so a cold
    # GTK IconTheme on Yurle cannot blank the transport controls.
    transport_icons = {
        "prev": "media-skip-backward",
        "play": "media-playback-start",
        "pause": "media-playback-pause",
        "next": "media-skip-forward",
    }

    def _set_button_icon(button: Gtk.Button, icon_name: str) -> None:
        image = button.get_image()
        if not isinstance(image, Gtk.Image):
            image = Gtk.Image()
            button.set_image(image)
            button.set_always_show_image(True)
        paint(image, icon_name, 12)

    original_make = active_window.ActiveWindowWidget._make_transport_button

    def _make_transport_button(self, label: str, tooltip: str) -> Gtk.Button:
        # Map legacy emoji labels from upstream call sites to symbolic icons.
        icon_name = transport_icons["play"]
        if label in {"⏮", "prev"}:
            icon_name = transport_icons["prev"]
        elif label in {"⏭", "next"}:
            icon_name = transport_icons["next"]
        elif label in {"⏸", "pause"}:
            icon_name = transport_icons["pause"]
        button = original_make(self, "", tooltip)
        button.set_label("")
        _set_button_icon(button, icon_name)
        return button

    def _sync_play_glyph(self) -> None:
        active = self._media_snapshot.active
        playing = (
            active is not None
            and active_window.is_strawberry_player(active)
            and active.status == "playing"
        )
        _set_button_icon(
            self._play_button,
            transport_icons["pause"] if playing else transport_icons["play"],
        )
        self._play_button.set_tooltip_text(
            "Pausar (Reproductor)" if playing else "Reproducir (Reproductor)"
        )

    def _paint_icon(self, icon_name: str) -> None:
        size = int(getattr(active_window, "ACTIVE_WINDOW_ICON_SIZE", 24) or 24)
        paint(self._icon, icon_name, size)

    original_window = active_window.ActiveWindowWidget._render_window
    original_media = active_window.ActiveWindowWidget._render_media
    original_idle = active_window.ActiveWindowWidget._render_player_idle

    def _render_window(self, window) -> None:
        original_window(self, window)
        _paint_icon(self, window.icon)

    def _render_media(self, player) -> None:
        original_media(self, player)
        name = (
            transport_icons["pause"]
            if player.status == "paused"
            else "audio-x-generic-symbolic"
        )
        _paint_icon(self, name)

    def _render_player_idle(self) -> None:
        original_idle(self)
        _paint_icon(self, "audio-x-generic-symbolic")

    active_window.ActiveWindowWidget._make_transport_button = _make_transport_button
    active_window.ActiveWindowWidget._sync_play_glyph = _sync_play_glyph
    active_window.ActiveWindowWidget._render_window = _render_window
    active_window.ActiveWindowWidget._render_media = _render_media
    active_window.ActiveWindowWidget._render_player_idle = _render_player_idle


def _apply_quiet_relaunch() -> None:
    """Replace in-process execv with a delayed respawn."""
    import shutil
    import subprocess

    import shell.runtime_relaunch as relaunch

    local = PATCHES / "runtime_relaunch.py"
    if local.is_file():
        spec = importlib.util.spec_from_file_location("_aidycos_relaunch", local)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            relaunch.relaunch_argv = module.relaunch_argv
            relaunch.relaunch_shell = module.relaunch_shell
            return

    def relaunch_shell() -> None:
        jugoo = shutil.which("jugoo")
        argv = [jugoo] if jugoo else [sys.executable, "-m", "shell", *sys.argv[1:]]
        subprocess.Popen(
            ["bash", "-c", 'sleep 0.45; exec "$@"', "jugoo-relaunch", *argv],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        import os

        os._exit(0)

    relaunch.relaunch_shell = relaunch_shell


def _apply_workspace_strip_defaults() -> None:
    """Live Hyprland list only — no reserved empty desktop dots 1–5."""
    try:
        import shell.config as config

        config.PERSISTENT_WORKSPACES = None
    except Exception as error:  # noqa: BLE001
        print(f"aidycos: workspace strip defaults skipped: {error}", flush=True)


def _apply_theme_reload_guard() -> None:
    """Skip ``hyprctl reload`` when the exported theme file did not change.

    Jugoo rewrites the theme and reloads Hyprland on every start. Login looks
    fine because apps are not open yet. ``jugoo action restart`` reloads while
    OnlyOffice is already mapped; on some GPUs (Yurle) the ribbon icons come
    back as yellow squares. AidyCSO's GPU redraws them, so the same restart
    looks healthy there.
    """
    import shell.ui.theme as theme_mod

    def _export_hyprland(self, theme) -> None:
        path = self._hypr_export_path
        if path is None:
            return
        try:
            previous = path.read_text(encoding="utf-8") if path.is_file() else ""
            theme_mod.export_hypr_theme(theme, path)
            if path.read_text(encoding="utf-8") == previous:
                return
            self._reload_hyprland()
        except (OSError, theme_mod.subprocess.SubprocessError) as error:
            print(f"Jugoo theme: Hyprland export skipped: {error}")

    theme_mod.ThemeManager._export_hyprland = _export_hyprland


def _append_user_icon_theme_paths() -> None:
    """Let Gtk resolve app icons installed under the user's XDG data directory."""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    from shell.user_icon_paths import append_user_icon_search_paths

    append_user_icon_search_paths(Gtk.IconTheme.get_default())


try:
    _append_user_icon_theme_paths()
except Exception as error:  # noqa: BLE001
    print(f"aidycos: user icon paths skipped: {error}", flush=True)


try:
    _apply_icons_patch()
except Exception as error:  # noqa: BLE001
    print(f"aidycos: icon patch skipped: {error}", flush=True)

try:
    _apply_session_menu_patches()
except Exception as error:  # noqa: BLE001
    print(f"aidycos: session menu patch skipped: {error}", flush=True)

_apply_workspace_strip_defaults()

try:
    _apply_theme_reload_guard()
except Exception as error:  # noqa: BLE001
    print(f"aidycos: theme reload guard skipped: {error}", flush=True)

try:
    _apply_workspace_icon_files()
except Exception as error:  # noqa: BLE001
    print(f"aidycos: workspace icon files skipped: {error}", flush=True)

try:
    _apply_active_window_icons()
except Exception as error:  # noqa: BLE001
    print(f"aidycos: active window icons skipped: {error}", flush=True)

try:
    _apply_quiet_relaunch()
except Exception as error:  # noqa: BLE001
    print(f"aidycos: quiet relaunch skipped: {error}", flush=True)

runpy.run_module("shell", run_name="__main__")
