#!/usr/bin/env python3
"""Draw the Calculadora icon at the hicolor sizes."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

TEAL = (11, 61, 74, 255)
MINT = (61, 220, 151, 255)
WHITE = (255, 255, 255, 255)
PALE = (232, 238, 240, 255)
CLEAR = (0, 0, 0, 0)


def _png(width: int, height: int, rows: list[bytes]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + row for row in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _inside_round_rect(x: float, y: float, left: float, top: float, right: float, bottom: float, radius: float) -> bool:
    if x < left or y < top or x > right or y > bottom:
        return False
    if left + radius <= x <= right - radius or top + radius <= y <= bottom - radius:
        return True
    corners = (
        (left + radius, top + radius),
        (right - radius, top + radius),
        (left + radius, bottom - radius),
        (right - radius, bottom - radius),
    )
    for cx, cy in corners:
        if (x - cx) ** 2 + (y - cy) ** 2 <= radius**2:
            return True
        if abs(x - cx) > radius or abs(y - cy) > radius:
            continue
    # Inside the corner square but outside the quarter circle.
    in_corner_square = (
        (x < left + radius and y < top + radius)
        or (x > right - radius and y < top + radius)
        or (x < left + radius and y > bottom - radius)
        or (x > right - radius and y > bottom - radius)
    )
    return not in_corner_square


def _sample(size: int, px: int, py: int) -> tuple[int, int, int, int]:
    # Supersample 3x so the small sizes stay readable.
    hits = [0, 0, 0, 0]
    total = 0
    for oy in range(3):
        for ox in range(3):
            x = (px + (ox + 0.5) / 3) / size
            y = (py + (oy + 0.5) / 3) / size
            color = _color_at(x, y)
            for channel in range(4):
                hits[channel] += color[channel]
            total += 1
    return tuple(channel // total for channel in hits)  # type: ignore[return-value]


def _color_at(x: float, y: float) -> tuple[int, int, int, int]:
    if not _inside_round_rect(x, y, 0.06, 0.06, 0.94, 0.94, 0.18):
        return CLEAR
    # Display.
    if _inside_round_rect(x, y, 0.18, 0.16, 0.82, 0.34, 0.04):
        return WHITE
    # Button grid: 3 columns x 3 rows, last cell is the equals key.
    cols = (0.18, 0.40, 0.62)
    rows = (0.44, 0.60, 0.76)
    for row, top in enumerate(rows):
        for col, left in enumerate(cols):
            if _inside_round_rect(x, y, left, top, left + 0.16, top + 0.12, 0.03):
                if row == 2 and col == 2:
                    return MINT
                return PALE if (row + col) % 2 == 0 else WHITE
    return TEAL


def render(size: int) -> bytes:
    rows = []
    for py in range(size):
        pixels = bytearray()
        for px in range(size):
            pixels.extend(_sample(size, px, py))
        rows.append(bytes(pixels))
    return _png(size, size, rows)


def main() -> None:
    root = Path(__file__).resolve().parent
    icons = root / "icons"
    icons.mkdir(exist_ok=True)
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        (icons / f"aidycalc-{size}.png").write_bytes(render(size))
    (root / "aidycalc.png").write_bytes((icons / "aidycalc-256.png").read_bytes())


if __name__ == "__main__":
    main()
