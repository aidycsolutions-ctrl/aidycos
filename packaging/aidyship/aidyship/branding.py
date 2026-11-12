"""Window class + theme icon for AidyShip."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

APP_ID = "aidyship"
APP_NAME = "AidyShip"
ICON_CANDIDATES = (
    Path("/usr/share/pixmaps/aidyship.png"),
    Path("/usr/share/icons/hicolor/256x256/apps/aidyship.png"),
    Path("/usr/share/icons/hicolor/128x128/apps/aidyship.png"),
    Path.home() / ".local/share/icons/hicolor/256x256/apps/aidyship.png",
    Path(__file__).resolve().parent.parent / "aidyship.png",
)

_applied = False


def apply_aidyship_branding(window: Gtk.Window | None = None) -> None:
    global _applied
    if not _applied:
        GLib.set_prgname(APP_ID)
        GLib.set_application_name(APP_NAME)
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
