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
        Path("/usr/local/share/applications") / name,
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
        ("Terminal", "application", "foot", "utilities-terminal"),
        ("Instalar paquetes", "application", "aidycos-paquetes", "system-software-install"),
        ("OnlyOffice", "application", "aidycos-onlyoffice", "x-office-document"),
    ]
    for name, kind, target, icon in candidates:
        if kind == "application" and not _app_exists(str(target)):
            if target == "firefox-esr" and _app_exists("firefox"):
                target = "firefox"
                icon = "firefox"
            elif target == "foot" and _app_exists("xfce4-terminal"):
                target = "xfce4-terminal"
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


def _read_icons_payload(path: Path) -> dict:
    if not path.is_file():
        return {"version": 1, "icons": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "icons": []}
    if not isinstance(payload, dict):
        return {"version": 1, "icons": []}
    icons = payload.get("icons")
    if not isinstance(icons, list):
        payload["icons"] = []
    payload.setdefault("version", 1)
    return payload


def _icon_keys(item: dict) -> set[str]:
    keys: set[str] = set()
    name = str(item.get("name") or "").strip().casefold()
    target = str(item.get("target") or "").strip().casefold()
    if name:
        keys.add(f"name:{name}")
    if target:
        keys.add(f"target:{target}")
        # Treat firefox / firefox-esr as the same shortcut.
        if target in {"firefox", "firefox-esr"}:
            keys.add("target:firefox")
            keys.add("target:firefox-esr")
    return keys


def merge_missing_default_icons(existing: list, defaults: list[dict[str, object]]) -> list:
    """Append default shortcuts that are not already present by name/target."""
    present: set[str] = set()
    merged: list = []
    for raw in existing:
        if isinstance(raw, dict):
            present |= _icon_keys(raw)
            merged.append(raw)

    max_y = 48
    for item in merged:
        if isinstance(item, dict):
            try:
                max_y = max(max_y, int(item.get("y") or 48))
            except (TypeError, ValueError):
                pass

    y = max_y + 104 if merged else 48
    for default in defaults:
        keys = _icon_keys(default)
        if keys & present:
            continue
        entry = dict(default)
        entry["x"] = int(entry.get("x") or 48)
        entry["y"] = y
        merged.append(entry)
        present |= keys
        y += 104
    return merged


def ensure_desktop_icons(
    path: Path,
    *,
    home: Path,
    reset: bool,
    clear: bool = False,
) -> bool:
    """Seed default shortcuts when missing/empty; preserve user-created icons."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if clear:
        path.write_text(
            json.dumps({"version": 1, "icons": []}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return True

    payload = _read_icons_payload(path)
    existing = payload.get("icons") if isinstance(payload.get("icons"), list) else []
    defaults = default_icons(home)
    if existing and not reset:
        merged = merge_missing_default_icons(existing, defaults)
        if merged == existing:
            return False
        payload = {"version": 1, "icons": merged}
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return True

    payload = {"version": 1, "icons": defaults}
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True


def ensure_icons_enabled(settings_path: Path, *, force: bool = False) -> bool:
    """Turn desktop icons on when unset, or when recovering a broken empty desktop."""
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

    current = values.get("escritorio.icons_enabled")
    if current is True and not force:
        return False
    # Respect an explicit user disable unless we are recovering empty desktops.
    if current is False and not force:
        return False

    values["escritorio.icons_enabled"] = True
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
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
        help="Vuelve a sembrar los iconos por defecto aunque ya existan",
    )
    parser.add_argument(
        "--clear-icons",
        action="store_true",
        help="Vacía desktop-icons.json (sin sembrar accesos)",
    )
    parser.add_argument(
        "--keep-icons",
        action="store_true",
        help="No tocar desktop-icons.json si ya existe (aunque esté vacío)",
    )
    args = parser.parse_args()

    root = data_dir()
    home = Path.home()
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
    before = _read_icons_payload(icons_path)
    before_icons = before.get("icons") if isinstance(before.get("icons"), list) else []
    was_empty = not before_icons
    if args.keep_icons and icons_path.is_file() and not args.reset_icons and not args.clear_icons:
        print(f"Iconos del escritorio conservados: {icons_path}")
        seeded = False
    else:
        seeded = ensure_desktop_icons(
            icons_path,
            home=home,
            reset=args.reset_icons,
            clear=args.clear_icons,
        )
        if seeded:
            changed = True
            if args.clear_icons:
                print(f"Iconos del escritorio vaciados: {icons_path}")
            else:
                print(f"Iconos del escritorio sembrados: {icons_path}")
        else:
            print(f"Iconos del escritorio conservados: {icons_path}")

    settings_path = root / "settings.json"
    # Older builds forced icons_enabled=False with an empty list; recover those.
    recover = (was_empty and seeded and not args.clear_icons) or args.reset_icons
    if ensure_icons_enabled(settings_path, force=recover):
        changed = True
        print("Iconos del escritorio activados en settings.json")

    return 0 if changed or chosen is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
