"""Desktop-entry to icon-theme-name resolution.

The returned values are icon *names*, never glyphs.  GTK resolves them through
the active Breeze/hicolor/XDG icon theme with ``Gtk.Image.new_from_icon_name``.

AidyCOS: map AidyC / AIDYCAI Tk windows to their logos, and avoid short
false positives like ``tk`` matching ``xdg-desktop-portal-gtk``.
"""

from __future__ import annotations

import configparser
import os
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from .models import Window


FALLBACK_ICON = "application-x-executable"
DESKTOP_ICON = "user-desktop"
KNOWN_APPLICATION_NAMES = {
    "aidyc": "AidyC",
    "aidycai": "AIDYCAI",
    "aidychat": "AidyChat",
    "aidycos-onlyoffice": "OnlyOffice",
    "onlyoffice": "OnlyOffice",
    "org.onlyoffice.desktopeditors": "OnlyOffice",
    "code-oss": "Code - OSS",
    "firefox": "Firefox",
    "kitty": "Kitty",
    "steam": "Steam",
}
_ONLYOFFICE_ICON = "org.onlyoffice.desktopeditors"
_ONLYOFFICE_INFO = None
_ONLYOFFICE_CLASSES = frozenset(
    {
        "onlyoffice",
        "desktopeditors",
        "onlyoffice-desktopeditors",
        "org.onlyoffice.desktopeditors",
        "aidycos-onlyoffice",
    }
)
_DEFAULT_XDG_DATA_DIRS = "/usr/local/share:/usr/share"
_FLATPAK_AND_SNAP_APPLICATION_DIRS = (
    Path.home() / ".local/share/flatpak/exports/share/applications",
    Path("/var/lib/flatpak/exports/share/applications"),
    Path("/var/lib/snapd/desktop/applications"),
)
_AIDYC_EXE_NAMES = frozenset({"aidyc", "AidyC"})
_AIDYC_EXE_PREFIXES = (
    Path("/opt/aidyc/AidyC"),
    Path("/usr/lib/aidyc"),
)
_AIDYC_TITLE = re.compile(r"^aidyc(?:\s|[0-9_]|$)", re.IGNORECASE)
_AIDYC_INFO = None  # filled lazily as ApplicationInfo("AidyC", "aidyc")
_AIDYCAI_TITLE = re.compile(r"^aidycai(?:\s|[—\-:]|$)", re.IGNORECASE)
_AIDYCAI_INFO = None


def application_directories() -> tuple[Path, ...]:
    """User, XDG, Flatpak, and Snap ``applications`` dirs. First path wins."""
    seen: set[Path] = set()
    ordered: list[Path] = []

    def add(path: Path) -> None:
        resolved = path.expanduser()
        if resolved in seen:
            return
        seen.add(resolved)
        ordered.append(resolved)

    data_home = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share"))
    add(data_home / "applications")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or _DEFAULT_XDG_DATA_DIRS
    for raw in data_dirs.split(":"):
        location = raw.strip()
        if location:
            add(Path(location) / "applications")
    for fallback in _FLATPAK_AND_SNAP_APPLICATION_DIRS:
        add(fallback)
    return tuple(ordered)


APPLICATION_DIRS = application_directories()


@dataclass(frozen=True)
class ApplicationInfo:
    name: str
    icon: str


class DesktopIconResolver:
    """Build a small WM_CLASS index once, then cache all resolution results."""

    def __init__(self, directories: Iterable[Path] | None = None) -> None:
        self._directories = tuple(directories) if directories is not None else application_directories()
        self._index: Dict[str, ApplicationInfo] | None = None
        self._cache: Dict[str, ApplicationInfo] = {}

    def describe(self, app_class: str) -> ApplicationInfo:
        key = app_class.casefold().strip()
        if not key:
            return ApplicationInfo("Aplicación", FALLBACK_ICON)
        if key not in self._cache:
            self._cache[key] = self._lookup(key) or ApplicationInfo(
                _friendly_application_name(app_class), FALLBACK_ICON
            )
        return self._cache[key]

    def _lookup(self, app_class: str) -> Optional[ApplicationInfo]:
        index = self._desktop_index()
        direct = index.get(app_class)
        if direct:
            return direct
        # Qualified ids (org.foo.Bar). Require 3+ chars so "tk" does not hit
        # "xdg-desktop-portal-gtk". Prefer the longest key and reject prefix
        # collisions like "aidyc" ⊂ "aidychat" (same icon / dock button).
        candidates: list[tuple[int, ApplicationInfo]] = []
        for name, info in index.items():
            if min(len(name), len(app_class)) < 3:
                continue
            if not _wm_class_matches(app_class, name):
                continue
            candidates.append((len(name), info))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _desktop_index(self) -> Dict[str, ApplicationInfo]:
        if self._index is not None:
            return self._index

        index: Dict[str, ApplicationInfo] = {}
        for directory in self._directories:
            if not directory.is_dir():
                continue
            for desktop_file in directory.glob("*.desktop"):
                entry = self._read_desktop_entry(desktop_file)
                if entry is None:
                    continue
                icon = entry.get("Icon", "").strip()
                if Path(icon).is_absolute():
                    icon = Path(icon).stem
                if not icon:
                    continue
                application = ApplicationInfo(
                    name=KNOWN_APPLICATION_NAMES.get(
                        desktop_file.stem.casefold(),
                        entry.get("Name", "").strip() or _friendly_application_name(desktop_file.stem),
                    ),
                    icon=icon,
                )
                names = (desktop_file.stem, entry.get("StartupWMClass", ""), application.name)
                for name in names:
                    normalized = name.casefold().strip()
                    if normalized:
                        index.setdefault(normalized, application)

        self._index = index
        return index

    @staticmethod
    def _read_desktop_entry(path: Path) -> configparser.SectionProxy | None:
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(path, encoding="utf-8")
            return parser["Desktop Entry"]
        except (OSError, KeyError, configparser.Error):
            return None


_resolver = DesktopIconResolver()


def icon_for_window(window: Window) -> str:
    """Return the system-theme icon name for a Hyprland client."""
    return application_for_window(window).icon


def application_for_window(window: Window) -> ApplicationInfo:
    """Return the desktop-entry identity shared by every shell widget."""
    onlyoffice = _onlyoffice_application(window)
    if onlyoffice is not None:
        return onlyoffice
    aidycai = _aidycai_application(window)
    if aidycai is not None:
        return aidycai
    aidyc = _aidyc_application(window)
    if aidyc is not None:
        return aidyc
    return _resolver.describe(window.app_class)


def _onlyoffice_application(window: Window) -> ApplicationInfo | None:
    """Map Hyprland class ONLYOFFICE to the Flatpak logo (not x-office-document)."""
    global _ONLYOFFICE_INFO
    app_class = (window.app_class or "").casefold().strip()
    if app_class not in _ONLYOFFICE_CLASSES:
        return None
    if _ONLYOFFICE_INFO is None:
        _ONLYOFFICE_INFO = ApplicationInfo("OnlyOffice", _ONLYOFFICE_ICON)
    return _ONLYOFFICE_INFO


def find_desktop_icon(app: str) -> str:
    """Compatibility entry point retained for external consumers of the old module."""
    return _resolver.describe(app).icon


_ICON_FILE_CACHE: dict[tuple[str, int], Path | None] = {}
_ICON_EXTS = (".png", ".svg", ".xpm", ".svgz")
_ICON_SIZE_DIRS = (
    "48x48",
    "64x64",
    "32x32",
    "128x128",
    "256x256",
    "24x24",
    "22x22",
    "16x16",
    "512x512",
    "scalable",
    "symbolic",
)
# GTK themes keep app logos under apps/, but media/transport and many
# fallbacks live in actions/mimetypes/…. Only searching apps/ left the
# center workspace pill blank on Yurle after a Jugoo restart.
_ICON_CONTEXT_DIRS = (
    "apps",
    "actions",
    "mimetypes",
    "status",
    "devices",
    "places",
    "categories",
    "legacy",
)


def resolve_icon_file(
    icon: str,
    size: int = 48,
    *,
    roots: tuple[Path, ...] | None = None,
) -> Path | None:
    """Find the icon on disk.

    The workspace pill asks GTK for a theme name. On a cold login the theme
    cache is already warm, so AidyCSO and the first paint on Yurle show Chrome
    and Cursor. After ``jugoo`` restarts, Yurle's GTK lookup comes back empty
    and the pill stays blank. A direct file still exists.
    """
    name = (icon or "").strip()
    if not name:
        return None
    cache_key = (name, int(size))
    if roots is None and cache_key in _ICON_FILE_CACHE:
        return _ICON_FILE_CACHE[cache_key]

    direct = Path(name).expanduser()
    if direct.is_file():
        if roots is None:
            _ICON_FILE_CACHE[cache_key] = direct
        return direct

    stem = Path(name).name
    if stem.endswith(_ICON_EXTS):
        stem = Path(stem).stem
    search_roots = roots if roots is not None else _icon_roots()
    found = _search_icon_dirs(stem, search_roots)
    if found is None and stem.endswith("-symbolic"):
        found = _search_icon_dirs(stem[: -len("-symbolic")], search_roots)
    if roots is None:
        _ICON_FILE_CACHE[cache_key] = found
    return found


def configure_workspace_icon(image: object, icon_name: str, pixel_size: int) -> None:
    """Paint a workspace-pill icon from a file, then fall back to the theme."""
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        gi.require_version("Gtk", "3.0")
        from gi.repository import GdkPixbuf, Gtk
    except (ImportError, ValueError):
        return
    size = max(1, int(pixel_size or 18))
    for candidate in (icon_name, FALLBACK_ICON):
        path = resolve_icon_file(candidate, size)
        if path is None:
            continue
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(str(path), size, size)
            image.set_from_pixbuf(pixbuf)
            image.set_pixel_size(size)
            return
        except Exception:
            continue
    image.set_from_icon_name(icon_name or FALLBACK_ICON, Gtk.IconSize.MENU)
    image.set_pixel_size(size)


def _icon_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    home = Path.home()
    roots.append(home / ".local/share")
    roots.append(home / ".local/share/flatpak/exports/share")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for raw in data_dirs.split(":"):
        location = raw.strip()
        if location:
            roots.append(Path(location))
    roots.append(Path("/var/lib/flatpak/exports/share"))
    seen: set[Path] = set()
    ordered: list[Path] = []
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        ordered.append(root)
    return tuple(ordered)


def _search_icon_dirs(stem: str, roots: tuple[Path, ...]) -> Path | None:
    names = tuple(f"{stem}{ext}" for ext in _ICON_EXTS)
    for root in roots:
        icons = root / "icons"
        pixmap = root / "pixmaps"
        for name in names:
            candidate = pixmap / name
            if candidate.is_file():
                return candidate
        if not icons.is_dir():
            continue
        # hicolor is the shared app-icon tree. Other themes are fallbacks.
        themes = [icons / "hicolor"]
        try:
            themes.extend(
                path for path in icons.iterdir() if path.is_dir() and path.name != "hicolor"
            )
        except OSError:
            continue
        for theme in themes:
            for size_dir in _ICON_SIZE_DIRS:
                for context in _ICON_CONTEXT_DIRS:
                    folder = theme / size_dir / context
                    if not folder.is_dir():
                        continue
                    for name in names:
                        candidate = folder / name
                        if candidate.is_file():
                            return candidate
    return None


def _wm_class_matches(app_class: str, name: str) -> bool:
    """True when desktop WM class / id reasonably matches a Hyprland class."""
    if app_class == name:
        return True
    if name in app_class:
        shorter, longer = name, app_class
    elif app_class in name:
        shorter, longer = app_class, name
    else:
        return False
    # "aidyc" must not claim "aidychat" / "aidycai".
    if longer.startswith(shorter):
        rest = longer[len(shorter) :]
        if rest and rest[0].isalnum():
            return False
    return True


def _friendly_application_name(app_class: str) -> str:
    normalized = app_class.casefold().strip()
    if normalized in KNOWN_APPLICATION_NAMES:
        return KNOWN_APPLICATION_NAMES[normalized]
    return " ".join(part.capitalize() for part in app_class.replace("_", " ").replace("-", " ").split())


def _aidyc_application(window: Window) -> ApplicationInfo | None:
    global _AIDYC_INFO
    if not _is_aidyc_window(window):
        return None
    if _AIDYC_INFO is None:
        _AIDYC_INFO = ApplicationInfo("AidyC", "aidyc")
    return _AIDYC_INFO


def _is_aidyc_window(window: Window) -> bool:
    app_class = (window.app_class or "").casefold().strip()
    # Never treat AidyChat / AIDYCAI as the AidyC IDE.
    if app_class.startswith("aidychat") or app_class.startswith("aidycai") or app_class.startswith("aidyship"):
        return False
    if app_class in {"aidyc", "com.aidyc.aidyc"}:
        return True
    if _exe_is_aidyc(getattr(window, "pid", None)):
        return True
    title = (window.title or "").strip()
    return bool(title and _AIDYC_TITLE.match(title))


def _exe_is_aidyc(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        exe = Path(f"/proc/{int(pid)}/exe").resolve()
    except (OSError, ValueError):
        return False
    if exe.name in _AIDYC_EXE_NAMES:
        return True
    return any(_path_is_relative_to(exe, prefix) for prefix in _AIDYC_EXE_PREFIXES)


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False

def _aidycai_application(window: Window) -> ApplicationInfo | None:
    global _AIDYCAI_INFO
    if not _is_aidycai_window(window):
        return None
    if _AIDYCAI_INFO is None:
        _AIDYCAI_INFO = ApplicationInfo("AIDYCAI", "aidycai")
    return _AIDYCAI_INFO


def _is_aidycai_window(window: Window) -> bool:
    app_class = (window.app_class or "").casefold().strip()
    if app_class in {"aidycai", "com.aidyc.aidycai"}:
        return True
    if _cmdline_has_aidycai(getattr(window, "pid", None)):
        return True
    title = (window.title or "").strip()
    return bool(title and _AIDYCAI_TITLE.match(title))


def _cmdline_has_aidycai(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
    except (OSError, ValueError):
        return False
    text = raw.replace(b"\x00", b" ").decode("utf-8", "ignore").casefold()
    return "aidycai" in text

