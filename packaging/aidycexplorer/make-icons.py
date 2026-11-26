#!/usr/bin/env python3
"""Build hicolor icons from the AidyCExplorer badge.

The source is a JPEG on a black square. Pixels outside the bright ring become
transparent so the circular badge does not sit in a black box. Black inside
the ring (letters and gaps) stays.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def _clear_outside_ring(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    pixels = image.load()
    width, height = image.size
    min_x, min_y, max_x, max_y = width, height, 0, 0
    found = False
    for y in range(height):
        for x in range(width):
            red, green, blue, _alpha = pixels[x, y]
            if max(red, green, blue) <= 48:
                continue
            found = True
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if not found:
        return image
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    radius = max(center_x - min_x, max_x - center_x, center_y - min_y, max_y - center_y) + 2
    for y in range(height):
        for x in range(width):
            distance = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
            if distance <= radius:
                continue
            red, green, blue, _alpha = pixels[x, y]
            pixels[x, y] = (red, green, blue, 0)
    return image


def prepare_master(source: Path) -> Image.Image:
    prepared = _clear_outside_ring(Image.open(source).convert("RGBA"))
    bbox = prepared.getbbox()
    if bbox:
        prepared = prepared.crop(bbox)
    pad = max(8, int(max(prepared.size) * 0.04))
    side = max(prepared.width, prepared.height) + pad * 2
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(
        prepared,
        ((side - prepared.width) // 2, (side - prepared.height) // 2),
        prepared,
    )
    return canvas


def _resize(image: Image.Image, size: int) -> Image.Image:
    """Resize straight RGBA without a dark fringe from the transparent surround."""
    image = image.convert("RGBA")
    pixels = image.load()
    width, height = image.size
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = pixels[x, y]
            if alpha in (0, 255):
                continue
            pixels[x, y] = (red * alpha // 255, green * alpha // 255, blue * alpha // 255, alpha)
    resized = image.resize((size, size), Image.Resampling.LANCZOS)
    pixels = resized.load()
    for y in range(size):
        for x in range(size):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                pixels[x, y] = (0, 0, 0, 0)
            elif alpha < 255:
                pixels[x, y] = (
                    min(255, red * 255 // alpha),
                    min(255, green * 255 // alpha),
                    min(255, blue * 255 // alpha),
                    alpha,
                )
    return resized


def main() -> None:
    root = Path(__file__).resolve().parent
    master = prepare_master(root / "source.jpg")
    icons = root / "icons"
    icons.mkdir(exist_ok=True)
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        _resize(master, size).save(icons / f"aidycexplorer-{size}.png", "PNG")
    _resize(master, 256).save(root / "aidycexplorer.png", "PNG")


if __name__ == "__main__":
    main()
