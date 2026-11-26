"""Filesystem operations for AidyCExplorer.

The window imports GTK; this module stays free of it so the file actions can
be tested without a display.
"""

from __future__ import annotations

import os
import shutil
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TRASH_URI = "trash://"

_ICON_BY_SUFFIX = {
    ".png": "image-x-generic",
    ".jpg": "image-x-generic",
    ".jpeg": "image-x-generic",
    ".gif": "image-x-generic",
    ".webp": "image-x-generic",
    ".svg": "image-x-generic",
    ".bmp": "image-x-generic",
    ".mp3": "audio-x-generic",
    ".wav": "audio-x-generic",
    ".ogg": "audio-x-generic",
    ".flac": "audio-x-generic",
    ".mp4": "video-x-generic",
    ".mkv": "video-x-generic",
    ".webm": "video-x-generic",
    ".avi": "video-x-generic",
    ".pdf": "application-pdf",
    ".zip": "package-x-generic",
    ".tar": "package-x-generic",
    ".gz": "package-x-generic",
    ".7z": "package-x-generic",
    ".deb": "package-x-generic",
    ".txt": "text-x-generic",
    ".md": "text-x-generic",
    ".py": "text-x-script",
    ".sh": "text-x-script",
    ".json": "text-x-generic",
    ".desktop": "application-x-desktop",
}


@dataclass(frozen=True)
class DirEntry:
    name: str
    path: Path
    is_dir: bool
    size: int | None
    mtime: float
    hidden: bool
    trash_name: str = ""
    origin: str = ""


def human_size(size: int | None) -> str:
    if size is None:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(size)} B"


def format_mtime(timestamp: float) -> str:
    if timestamp <= 0:
        return ""
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def icon_name_for(entry: DirEntry) -> str:
    if entry.is_dir:
        return "folder"
    return _ICON_BY_SUFFIX.get(entry.path.suffix.casefold(), "text-x-generic")


def validate_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\x00" in cleaned:
        raise ValueError("El nombre no es válido")
    return cleaned


def list_directory(path: Path, *, show_hidden: bool = False) -> list[DirEntry]:
    path = Path(path)
    if not path.is_dir():
        raise NotADirectoryError(str(path))
    entries: list[DirEntry] = []
    for child in path.iterdir():
        hidden = child.name.startswith(".")
        if hidden and not show_hidden:
            continue
        entries.append(_entry_for(child, hidden=hidden))
    entries.sort(key=lambda item: (not item.is_dir, item.name.casefold()))
    return entries


def _entry_for(child: Path, *, hidden: bool, trash_name: str = "", origin: str = "") -> DirEntry:
    try:
        stat = child.stat()
        is_dir = child.is_dir()
        size = None if is_dir else int(stat.st_size)
        mtime = float(stat.st_mtime)
    except OSError:
        is_dir = False
        size = None
        mtime = 0
    return DirEntry(
        name=child.name if not origin else Path(origin).name,
        path=child,
        is_dir=is_dir,
        size=size,
        mtime=mtime,
        hidden=hidden,
        trash_name=trash_name,
        origin=origin,
    )


def split_name(name: str) -> tuple[str, str]:
    if name.startswith(".") and name.count(".") == 1:
        return name, ""
    suffix = Path(name).suffix
    if suffix and not name.startswith("."):
        return name[: -len(suffix)], suffix
    return name, ""


def unique_destination(directory: Path, name: str) -> Path:
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = split_name(name)
    number = 2
    while True:
        if number == 2:
            labeled = f"{stem} (copia){suffix}"
        else:
            labeled = f"{stem} (copia {number - 1}){suffix}"
        candidate = directory / labeled
        if not candidate.exists():
            return candidate
        number += 1


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def copy_entry(src: Path, dest_dir: Path) -> Path:
    src = Path(src)
    dest_dir = Path(dest_dir)
    if not src.exists() and not src.is_symlink():
        raise FileNotFoundError(str(src))
    if src.is_dir() and not src.is_symlink() and _contains(src, dest_dir):
        raise ValueError("No se puede copiar una carpeta dentro de sí misma")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_destination(dest_dir, src.name)
    if src.is_dir() and not src.is_symlink():
        shutil.copytree(src, dest, symlinks=True)
    else:
        shutil.copy2(src, dest, follow_symlinks=False)
    return dest


def move_entry(src: Path, dest_dir: Path) -> Path:
    src = Path(src)
    dest_dir = Path(dest_dir)
    if not src.exists() and not src.is_symlink():
        raise FileNotFoundError(str(src))
    if src.is_dir() and not src.is_symlink() and _contains(src, dest_dir):
        raise ValueError("No se puede mover una carpeta dentro de sí misma")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_destination(dest_dir, src.name)
    shutil.move(str(src), str(dest))
    return dest


def rename_entry(src: Path, new_name: str) -> Path:
    src = Path(src)
    name = validate_name(new_name)
    if not src.exists() and not src.is_symlink():
        raise FileNotFoundError(str(src))
    dest = src.with_name(name)
    if dest.exists() and dest != src:
        raise ValueError("Ya existe un elemento con ese nombre")
    src.rename(dest)
    return dest


def make_directory(parent: Path, name: str) -> Path:
    parent = Path(parent)
    folder = parent / validate_name(name)
    folder.mkdir(parents=False, exist_ok=False)
    return folder


def assert_protected(path: Path) -> None:
    absolute = Path(path).absolute()
    if absolute == Path("/") or absolute == Path.home():
        raise ValueError("Esa carpeta no se puede borrar")


def delete_path(path: Path) -> None:
    path = Path(path)
    assert_protected(path)
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    raise FileNotFoundError(str(path))


def trash_root_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "Trash"


def trash_files_path(root: Path | None = None) -> Path:
    files, _info = _trash_dirs(root)
    return files


def _trash_dirs(root: Path | None = None) -> tuple[Path, Path]:
    base = Path(root) if root is not None else trash_root_dir()
    files = base / "files"
    info = base / "info"
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    return files, info


def move_to_trash(path: Path, trash_root: Path | None = None) -> Path:
    path = Path(path).absolute()
    assert_protected(path)
    if not path.exists() and not path.is_symlink():
        raise FileNotFoundError(str(path))
    files, info = _trash_dirs(trash_root)
    if _contains(files.parent, path):
        raise ValueError("Ese elemento ya está en la papelera")
    dest_name = path.name or "elemento"
    number = 1
    while (files / dest_name).exists() or (info / f"{dest_name}.trashinfo").exists():
        number += 1
        dest_name = f"{path.name}_{number}"
    dest = files / dest_name
    shutil.move(str(path), str(dest))
    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    encoded = urllib.parse.quote(str(path), safe="/")
    (info / f"{dest_name}.trashinfo").write_text(
        f"[Trash Info]\nPath={encoded}\nDeletionDate={stamp}\n",
        encoding="utf-8",
    )
    return dest


def _read_trashinfo(path: Path) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Path="):
            return urllib.parse.unquote(line.split("=", 1)[1].strip())
    return ""


def list_trash(trash_root: Path | None = None) -> list[DirEntry]:
    files, info = _trash_dirs(trash_root)
    entries: list[DirEntry] = []
    for child in files.iterdir():
        origin = _read_trashinfo(info / f"{child.name}.trashinfo")
        entry = _entry_for(child, hidden=False, trash_name=child.name, origin=origin)
        display = Path(origin).name if origin else child.name
        entries.append(
            DirEntry(
                name=display,
                path=entry.path,
                is_dir=entry.is_dir,
                size=entry.size,
                mtime=entry.mtime,
                hidden=entry.hidden,
                trash_name=child.name,
                origin=origin,
            )
        )
    entries.sort(key=lambda item: (not item.is_dir, item.name.casefold()))
    return entries


def restore_trash(trash_name: str, trash_root: Path | None = None) -> Path:
    files, info = _trash_dirs(trash_root)
    src = files / trash_name
    if not src.exists() and not src.is_symlink():
        raise FileNotFoundError(trash_name)
    meta = info / f"{trash_name}.trashinfo"
    origin = _read_trashinfo(meta)
    target = Path(origin) if origin else Path.home() / src.name
    target.parent.mkdir(parents=True, exist_ok=True)
    dest = target if not target.exists() else unique_destination(target.parent, target.name)
    shutil.move(str(src), str(dest))
    meta.unlink(missing_ok=True)
    return dest


def delete_trash_item(trash_name: str, trash_root: Path | None = None) -> None:
    files, info = _trash_dirs(trash_root)
    target = files / trash_name
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    (info / f"{trash_name}.trashinfo").unlink(missing_ok=True)


def user_places(home: Path | None = None) -> list[tuple[str, Path]]:
    home = Path(home) if home is not None else Path.home()
    mapping = _read_user_dirs(home)
    specs = (
        ("Inicio", home),
        ("Escritorio", mapping.get("DESKTOP", home / "Desktop")),
        ("Documentos", mapping.get("DOCUMENTS", home / "Documents")),
        ("Descargas", mapping.get("DOWNLOADS", home / "Downloads")),
        ("Imágenes", mapping.get("PICTURES", home / "Pictures")),
        ("Música", mapping.get("MUSIC", home / "Music")),
        ("Vídeos", mapping.get("VIDEOS", home / "Videos")),
    )
    places: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for label, path in specs:
        folder = Path(path).expanduser()
        if not folder.is_dir():
            continue
        key = str(folder)
        if key in seen:
            continue
        seen.add(key)
        places.append((label, folder))
    return places


def _read_user_dirs(home: Path) -> dict[str, Path]:
    config = home / ".config" / "user-dirs.dirs"
    found: dict[str, Path] = {}
    if not config.is_file():
        return found
    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        value = value.strip().strip('"').replace("${HOME}", str(home)).replace("$HOME", str(home))
        short = key.removeprefix("XDG_").removesuffix("_DIR")
        found[short] = Path(value)
    return found


def parse_location(text: str, *, home: Path, cwd: Path | None = None) -> tuple[str, Path]:
    raw = text.strip()
    if not raw:
        raise ValueError("Escribe una ruta")
    if raw.casefold() in {"trash://", "trash:", "papelera"}:
        return "trash", trash_root_dir() / "files"
    if raw.startswith("file:"):
        parsed = urllib.parse.urlparse(raw)
        raw = urllib.parse.unquote(parsed.path or "")
        if not raw:
            raise ValueError("La dirección no tiene ruta")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (cwd or home) / path
    return "path", path


def resolve_start(
    locations: list[str] | None,
    *,
    home: Path | None = None,
) -> tuple[str, Path, str | None]:
    """Return mode, directory, and the file name to select."""
    home = Path(home) if home is not None else Path.home()
    if not locations:
        return "path", home, None
    mode, path = parse_location(locations[0], home=home, cwd=home)
    if mode == "trash":
        return "trash", path, None
    if path.is_file():
        return "path", path.parent, path.name
    return "path", path, None
