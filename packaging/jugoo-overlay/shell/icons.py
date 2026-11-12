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
    "code-oss": "Code - OSS",
    "firefox": "Firefox",
    "kitty": "Kitty",
    "steam": "Steam",
}
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
        # "xdg-desktop-portal-gtk".
        return next(
            (
                info
                for name, info in index.items()
                if min(len(name), len(app_class)) >= 3
                and (name in app_class or app_class in name)
            ),
            None,
        )

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
    aidycai = _aidycai_application(window)
    if aidycai is not None:
        return aidycai
    aidyc = _aidyc_application(window)
    if aidyc is not None:
        return aidyc
    return _resolver.describe(window.app_class)


def find_desktop_icon(app: str) -> str:
    """Compatibility entry point retained for external consumers of the old module."""
    return _resolver.describe(app).icon


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

