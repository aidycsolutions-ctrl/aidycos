"""Window class and theme icon for AidyCExplorer."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

APP_ID = "aidycexplorer"
APP_NAME = "AidyCExplorer"
ICON_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "aidycexplorer.png",
    Path("/usr/share/pixmaps/aidycexplorer.png"),
    Path("/usr/share/icons/hicolor/256x256/apps/aidycexplorer.png"),
    Path("/usr/share/icons/hicolor/128x128/apps/aidycexplorer.png"),
    Path.home() / ".local/share/pixmaps/aidycexplorer.png",
    Path.home() / ".local/share/icons/hicolor/256x256/apps/aidycexplorer.png",
    Path.home() / ".local/share/icons/hicolor/128x128/apps/aidycexplorer.png",
    Path.home() / ".local/share/aidycexplorer/aidycexplorer.png",
)

_applied = False


def resolve_icon_path() -> Path | None:
    for path in ICON_CANDIDATES:
        if path.is_file():
            return path
    return None


def load_logo_pixbuf(size: int = 28) -> GdkPixbuf.Pixbuf | None:
    path = resolve_icon_path()
    if path is None:
        return None
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), size, size, True)
    except GLib.Error:
        return None


def apply_branding(window: Gtk.Window | None = None) -> None:
    global _applied
    icon = resolve_icon_path()
    if not _applied:
        GLib.set_prgname(APP_ID)
        GLib.set_application_name(APP_NAME)
        try:
            Gdk.set_program_class(APP_ID)
        except AttributeError:
            pass
        Gtk.Window.set_default_icon_name(APP_ID)
        if icon is not None:
            try:
                Gtk.Window.set_default_icon_from_file(str(icon))
            except GLib.Error:
                pass
        _applied = True

    if window is None:
        return
    window.set_wmclass(APP_ID, APP_ID)
    window.set_icon_name(APP_ID)
    if icon is not None:
        try:
            window.set_icon_from_file(str(icon))
        except GLib.Error:
            pass
