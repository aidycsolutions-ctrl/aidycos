"""Window class + theme icon for AidyChat (taskbar / title bar)."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

APP_ID = "aidychat"
ICON_CANDIDATES = (
    Path("/usr/share/pixmaps/aidychat.png"),
    Path("/usr/share/icons/hicolor/256x256/apps/aidychat.png"),
    Path("/usr/share/icons/hicolor/128x128/apps/aidychat.png"),
    Path.home() / ".local/share/icons/hicolor/256x256/apps/aidychat.png",
    Path(__file__).resolve().parent.parent / "aidychat.png",
)

_applied = False


def apply_aidychat_branding(window: Gtk.Window | None = None) -> None:
    """Set Wayland/X11 app id and the AidyChat logo on the process / window."""
    global _applied
    if not _applied:
        GLib.set_prgname(APP_ID)
        GLib.set_application_name("AidyChat")
        try:
            Gdk.set_program_class(APP_ID)
        except AttributeError:
            pass
        Gtk.Window.set_default_icon_name(APP_ID)
        for path in ICON_CANDIDATES:
            if path.is_file():
                try:
                    Gtk.Window.set_default_icon_from_file(str(path))
                    break
                except GLib.Error:
                    continue
        _applied = True

    if window is None:
        return
    window.set_wmclass(APP_ID, APP_ID)
    window.set_icon_name(APP_ID)
    for path in ICON_CANDIDATES:
        if path.is_file():
            try:
                window.set_icon_from_file(str(path))
                break
            except GLib.Error:
                continue
