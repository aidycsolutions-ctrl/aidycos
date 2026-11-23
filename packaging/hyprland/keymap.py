"""Hyprland keymap that delivers keypad Intro (KP_Enter) as Return."""

from __future__ import annotations

import re
from pathlib import Path

KEYMAP_NAME = "aidycos-keymap.xkb"
KEYMAP_REF = "~/.config/hypr/aidycos-keymap.xkb"
DEFAULT_LAYOUT = "latam"

_LAYOUT_RE = re.compile(r"(?m)^\s*kb_layout\s*=\s*(\S+)\s*$")
_VARIANT_RE = re.compile(r"(?m)^\s*kb_variant\s*=\s*(\S+)\s*$")
_KB_FILE_RE = re.compile(r"(?m)^\s*kb_file\s*=")
_INPUT_RE = re.compile(r"(?m)^(?P<indent>\s*)input\s*\{")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def layout_token(raw: str, default: str = DEFAULT_LAYOUT) -> str:
    token = (raw or "").split(",")[0].strip()
    if _TOKEN_RE.fullmatch(token):
        return token
    return default


def symbols_include(layout: str, variant: str = "") -> str:
    layout_name = layout_token(layout)
    variant_name = (variant or "").split(",")[0].strip().strip("'\"")
    if variant_name and not _TOKEN_RE.fullmatch(variant_name):
        variant_name = ""
    if variant_name:
        return f"{layout_name}({variant_name})"
    return layout_name


def render_keymap(layout: str = DEFAULT_LAYOUT, variant: str = "") -> str:
    """XKB keymap for ``layout`` where <KPEN> is Return.

    The main Enter key already emits Return. Keypad Intro emits KP_Enter, and
    most fields only activate on Return. ``kb_file`` replaces kb_layout, so
    the keymap keeps the same letters and only remaps that one key.
    """
    symbols = symbols_include(layout, variant)
    return (
        "xkb_keymap {\n"
        '    xkb_keycodes { include "evdev+aliases(qwerty)" };\n'
        '    xkb_types    { include "complete" };\n'
        '    xkb_compat   { include "complete" };\n'
        f'    xkb_symbols  {{ include "pc+{symbols}+inet(evdev)"\n'
        "        key <KPEN> { [ Return ] };\n"
        "    };\n"
        '    xkb_geometry { include "pc(pc105)" };\n'
        "};\n"
    )


def read_layout(text: str) -> tuple[str, str]:
    layouts = _LAYOUT_RE.findall(text)
    variants = _VARIANT_RE.findall(text)
    layout = layouts[-1] if layouts else DEFAULT_LAYOUT
    variant = variants[-1] if variants else ""
    if variant.strip("'\"") == "":
        variant = ""
    return layout, variant


def ensure_kb_file(text: str, keymap_ref: str = KEYMAP_REF) -> str:
    """Insert ``kb_file`` into the first input block when it is absent.

    A hand-written ``kb_file`` is left alone.
    """
    desired = f"kb_file = {keymap_ref}"
    if re.search(rf"(?m)^\s*{re.escape(desired)}\s*$", text):
        return text
    if _KB_FILE_RE.search(text):
        return text
    match = _INPUT_RE.search(text)
    if not match:
        base = text
        if base and not base.endswith("\n"):
            base += "\n"
        if base and not base.endswith("\n\n"):
            base += "\n"
        return base + f"input {{\n    {desired}\n}}\n"
    indent = match.group("indent")
    insert_at = match.end()
    return text[:insert_at] + f"\n{indent}    {desired}" + text[insert_at:]


def apply_to_config_dir(hypr_dir: Path) -> tuple[Path, list[Path]]:
    """Write the keymap and point hyprland.conf / aidycos.conf at it."""
    hypr_dir = Path(hypr_dir)
    hypr_dir.mkdir(parents=True, exist_ok=True)
    confs = [hypr_dir / "hyprland.conf", hypr_dir / "aidycos.conf"]
    combined = ""
    for path in confs:
        if path.is_file():
            combined += "\n" + path.read_text(encoding="utf-8")
    layout, variant = read_layout(combined)
    keymap_path = hypr_dir / KEYMAP_NAME
    keymap_path.write_text(render_keymap(layout, variant), encoding="utf-8")
    changed: list[Path] = []
    for path in confs:
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        updated = ensure_kb_file(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return keymap_path, changed
