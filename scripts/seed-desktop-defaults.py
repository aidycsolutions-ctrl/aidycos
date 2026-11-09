#!/usr/bin/env python3
"""Seed AidyCOS desktop wallpaper + sensible desktop icons when missing."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import uuid
from pathlib import Path


DEFAULT_WALLPAPER = Path("/usr/share/backgrounds/aidycos.png")
FALLBACK_WALLPAPERS = (
    Path("/usr/share/backgrounds/aidycos.png"),
    Path("/usr/share/desktop-base/ceratopsian-theme/wallpaper/contents/images/1920x1080.svg"),
    Path("/usr/share/images/desktop-base/desktop-background"),
)


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "waybar-shell"


def wallpaper_candidates(explicit: Path | None) -> list[Path]:
    items: list[Path] = []
    if explicit is not None:
        items.append(explicit)
    items.extend(FALLBACK_WALLPAPERS)
    return items


def ensure_wallpaper_setting(settings_path: Path, wallpaper: Path) -> bool:
    payload: dict
    if settings_path.is_file():
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"version": 1, "values": {}}
    else:
        payload = {"version": 1, "values": {}}
    values = payload.setdefault("values", {})
    if not isinstance(values, dict):
        values = {}
        payload["values"] = values
    current = str(values.get("escritorio.wallpaper_path") or "").strip()
    if current and Path(current).expanduser().is_file():
        return False
    values["escritorio.wallpaper_path"] = str(wallpaper)
    values.setdefault("escritorio.wallpaper_fill", "crop")
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True


def install_wallpaper_copy(source: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob("current.*"):
        if old.is_file():
            old.unlink(missing_ok=True)
    dest = dest_dir / f"current{source.suffix.casefold() or '.png'}"
    shutil.copy2(source, dest)
    return dest


def _app_exists(desktop_id: str) -> bool:
    name = desktop_id if desktop_id.endswith(".desktop") else f"{desktop_id}.desktop"
    search = [
        Path("/usr/share/applications") / name,
        Path.home() / ".local/share/applications" / name,
    ]
    return any(path.is_file() for path in search)


def default_icons(home: Path) -> list[dict[str, object]]:
    icons: list[dict[str, object]] = []
    y = 48
    candidates = [
        ("AidyChat", "application", "aidychat", "aidychat"),
        ("Firefox", "application", "firefox-esr", "firefox-esr"),
        ("Archivos", "directory", str(home), "user-home"),
        ("Terminal", "application", "xfce4-terminal", "utilities-terminal"),
    ]
    for name, kind, target, icon in candidates:
        if kind == "application" and not _app_exists(str(target)):
            if target == "firefox-esr" and _app_exists("firefox"):
                target = "firefox"
                icon = "firefox"
            else:
                continue
        if kind == "directory" and not Path(str(target)).is_dir():
            continue
        icons.append(
            {
                "id": uuid.uuid4().hex,
                "name": name,
                "type": kind,
                "target": target,
                "icon": icon,
                "x": 48,
                "y": y,
            }
        )
        y += 104
    return icons


def ensure_desktop_icons(path: Path, *, reset: bool) -> bool:
    if path.is_file() and not reset:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        icons = payload.get("icons") if isinstance(payload, dict) else payload
        if isinstance(icons, list) and icons:
            return False
    icons = default_icons(Path.home())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "icons": icons}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wallpaper",
        type=Path,
        default=DEFAULT_WALLPAPER,
        help="Imagen de fondo por defecto",
    )
    parser.add_argument(
        "--reset-icons",
        action="store_true",
        help="Reescribe desktop-icons.json aunque ya existan iconos",
    )
    args = parser.parse_args()

    root = data_dir()
    chosen: Path | None = None
    for candidate in wallpaper_candidates(args.wallpaper):
        if candidate.is_file():
            chosen = candidate
            break
    changed = False
    if chosen is not None:
        installed = install_wallpaper_copy(chosen, root / "wallpapers")
        if ensure_wallpaper_setting(root / "settings.json", installed):
            changed = True
            print(f"Fondo de escritorio: {installed}")
        else:
            print(f"Fondo ya configurado; copia actualizada en {installed}")
    else:
        print("No se encontró imagen de fondo por defecto.", flush=True)

    icons_path = root / "desktop-icons.json"
    if ensure_desktop_icons(icons_path, reset=args.reset_icons):
        changed = True
        print(f"Iconos del escritorio: {icons_path}")
    else:
        print(f"Iconos del escritorio conservados: {icons_path}")

    return 0 if changed or chosen is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
