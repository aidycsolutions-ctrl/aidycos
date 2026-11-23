"""Recognize a screenshot or image file sitting on the clipboard."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def target_includes_image(names: list[str]) -> bool:
    """True when the clipboard offers pixel data, not just text."""
    for name in names:
        base = str(name or "").split(";", 1)[0].strip().lower()
        if base.startswith("image/"):
            return True
        if base in {"application/x-qt-image"}:
            return True
    return False


def image_file_from_uris(uris: list[str]) -> str | None:
    """First file:// URI that points at an image, or None."""
    for uri in uris:
        parsed = urlparse(uri or "")
        if parsed.scheme != "file" or not parsed.path:
            continue
        path = unquote(parsed.path)
        if Path(path).suffix.lower() in IMAGE_SUFFIXES:
            return path
    return None
