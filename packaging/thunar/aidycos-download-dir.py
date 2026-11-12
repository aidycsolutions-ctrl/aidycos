#!/usr/bin/env python3
"""Keep browser downloads on one XDG folder and poke Thunar after finalize.

Browsers write ``*.crdownload`` / ``*.part`` then rename to the final name.
Thunar's folder monitor sometimes misses that rename on Hyprland sessions, so
the file looks "gone" until something else refreshes the view. Watching the
download dir and briefly creating a hidden marker forces a listing refresh.

Also collapses the common ``Downloads`` vs ``Descargas`` split when safe, so
Chrome/Firefox and Thunar bookmarks point at the same place.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

_PARTIAL_SUFFIXES = (".crdownload", ".part", ".download", ".tmp")
_USER_DIRS_LINE = re.compile(
    r'^XDG_DOWNLOAD_DIR\s*=\s*("?)([^"\n]*)\1\s*$',
    re.MULTILINE,
)


def _home() -> Path:
    return Path.home()


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (_home() / ".config"))


def preferred_download_name(home: Path | None = None) -> str:
    """Pick Descargas for Spanish locales; otherwise Downloads, with existing dirs winning."""
    root = home or _home()
    descargas = root / "Descargas"
    downloads = root / "Downloads"
    lang = (
        os.environ.get("LC_ALL")
        or os.environ.get("LC_MESSAGES")
        or os.environ.get("LANG")
        or ""
    ).casefold()
    if lang.startswith("es"):
        return "Descargas"
    if descargas.exists() and not downloads.exists():
        return "Descargas"
    if downloads.exists() and not descargas.exists():
        return "Downloads"
    # AidyCOS UI is Spanish-first.
    return "Descargas"


def _dir_has_user_entries(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        next(path.iterdir())
    except StopIteration:
        return False
    except OSError:
        return True
    return True


def _safe_replace_with_symlink(path: Path, target: Path) -> None:
    """Replace an empty real directory (or missing path) with a symlink to target."""
    if path.is_symlink():
        try:
            if path.resolve() == target.resolve():
                return
        except OSError:
            pass
        path.unlink()
    elif path.is_dir():
        if _dir_has_user_entries(path):
            return
        path.rmdir()
    elif path.exists():
        return
    path.symlink_to(target, target_is_directory=True)


def resolve_download_dir(home: Path | None = None) -> Path:
    root = home or _home()
    name = preferred_download_name(root)
    return (root / name).resolve() if (root / name).exists() else root / name


def ensure_download_dir(home: Path | None = None) -> Path:
    """Create/unify the XDG download folder and return the canonical path."""
    root = home or _home()
    preferred = root / preferred_download_name(root)
    other_name = "Downloads" if preferred.name == "Descargas" else "Descargas"
    other = root / other_name

    if shutil_which("xdg-user-dirs-update"):
        try:
            subprocess.run(
                ["xdg-user-dirs-update"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    if not preferred.exists() and other.exists() and not other.is_symlink():
        # Adopt the English/Spanish sibling as the canonical folder.
        other.rename(preferred)
    preferred.mkdir(parents=True, exist_ok=True)
    _safe_replace_with_symlink(other, preferred)

    _write_user_dirs_download(preferred)
    _ensure_gtk_bookmark(preferred)
    return preferred


def _write_user_dirs_download(download_dir: Path) -> None:
    path = _config_home() / "user-dirs.dirs"
    path.parent.mkdir(parents=True, exist_ok=True)
    home = _home()
    try:
        rel = download_dir.resolve().relative_to(home.resolve())
        value = f'$HOME/{rel.as_posix()}'
    except ValueError:
        value = str(download_dir)

    line = f'XDG_DOWNLOAD_DIR="{value}"\n'
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if _USER_DIRS_LINE.search(text):
            text = _USER_DIRS_LINE.sub(line.rstrip(), text)
            if not text.endswith("\n"):
                text += "\n"
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += line
    else:
        text = (
            "# This file is written by xdg-user-dirs-update\n"
            "# AidyCOS keeps XDG_DOWNLOAD_DIR aligned with Descargas/Downloads.\n"
            f"{line}"
        )
    path.write_text(text, encoding="utf-8")


def _ensure_gtk_bookmark(download_dir: Path) -> None:
    bookmarks = _config_home() / "gtk-3.0" / "bookmarks"
    bookmarks.parent.mkdir(parents=True, exist_ok=True)
    uri = download_dir.resolve().as_uri()
    label = download_dir.name
    entry = f"{uri} {label}"
    lines: list[str] = []
    if bookmarks.is_file():
        lines = bookmarks.read_text(encoding="utf-8").splitlines()
    # Drop stale Downloads/Descargas bookmarks that point elsewhere.
    filtered: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        bookmark_uri = parts[0]
        if bookmark_uri.rstrip("/").endswith(("/Downloads", "/Descargas")):
            continue
        if bookmark_uri.rstrip("/") == uri.rstrip("/"):
            continue
        filtered.append(raw.rstrip())
    filtered.insert(0, entry)
    bookmarks.write_text("\n".join(filtered) + "\n", encoding="utf-8")


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def _is_partial_name(name: str) -> bool:
    lowered = name.casefold()
    return any(lowered.endswith(suffix) for suffix in _PARTIAL_SUFFIXES)


def _poke_directory(path: Path) -> None:
    """Force folder monitors to re-list without showing a visible file."""
    marker = path / ".aidycos-dl-refresh"
    try:
        marker.write_bytes(b"")
        marker.unlink(missing_ok=True)
    except OSError:
        try:
            os.utime(path, None)
        except OSError:
            pass


def watch_download_dir(download_dir: Path | None = None) -> int:
    """Watch the download folder and poke it when browser partials finalize."""
    try:
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError) as error:
        print(f"aidycos-download-dir: Gio unavailable ({error})", file=sys.stderr)
        return 1

    target = download_dir or ensure_download_dir()
    target.mkdir(parents=True, exist_ok=True)

    pending: dict[str, int] = {}

    def schedule_poke(name: str) -> None:
        # Coalesce bursts (Chrome may emit several events per finalize).
        token = pending.get(name, 0) + 1
        pending[name] = token

        def _run(expected: int = token) -> bool:
            if pending.get(name) != expected:
                return False
            pending.pop(name, None)
            _poke_directory(target)
            return False

        GLib.timeout_add(150, _run)

    renamed = getattr(Gio.FileMonitorEvent, "RENAMED", None)

    def on_changed(monitor, file, other_file, event_type, *_args) -> None:
        del monitor
        try:
            name = file.get_basename() or ""
        except Exception:
            return
        if name == ".aidycos-dl-refresh":
            return
        other_name = ""
        if other_file is not None:
            try:
                other_name = other_file.get_basename() or ""
            except Exception:
                other_name = ""
        interesting = event_type in (
            Gio.FileMonitorEvent.MOVED,
            Gio.FileMonitorEvent.DELETED,
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
        ) or (renamed is not None and event_type == renamed)
        if not interesting:
            return
        # Only act on browser partials; a poke after *.crdownload/*.part settles
        # makes Thunar re-list so the final name shows up.
        if _is_partial_name(name) or _is_partial_name(other_name):
            schedule_poke(name or other_name or "*")

    gfile = Gio.File.new_for_path(str(target))
    flags = Gio.FileMonitorFlags.WATCH_MOVES
    monitor = gfile.monitor_directory(flags, None)
    monitor.connect("changed", on_changed)

    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ensure_p = sub.add_parser("ensure", help="Unify Descargas/Downloads and seed bookmarks")
    ensure_p.add_argument("--print-path", action="store_true", help="Print canonical path")

    watch_p = sub.add_parser("watch", help="Watch download dir and refresh Thunar listings")
    watch_p.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="Override download directory (default: XDG / ensured path)",
    )

    args = parser.parse_args(argv)
    if args.command == "ensure":
        path = ensure_download_dir()
        if args.print_path:
            print(path)
        return 0
    if args.command == "watch":
        # Ensure first so watch always follows the canonical folder.
        ensured = ensure_download_dir()
        return watch_download_dir(args.dir or ensured)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
