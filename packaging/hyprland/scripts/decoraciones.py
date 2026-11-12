"""Decide which windows already draw their own minimize / maximize / close."""

from __future__ import annotations

import re
from collections.abc import Iterable

# Apps known to paint caption buttons (min + max + close) inside the client.
# Do not add broad toolkit heuristics here: GNOME/libadwaita often omit minimize
# unless gtk-decoration-layout is set, and /proc maps false-positives (zenity).
_CSD_CLASS = re.compile(
    r"^(?:"
    r"google-chrome(?:-[\w-]+)?|chrome-[\w-]+|chromium(?:-browser)?|brave-browser|"
    r"microsoft-edge|vivaldi|"
    r"firefox(?:-esr)?|org\.mozilla\.firefox|librewolf|zen|"
    r"cursor|code|code-oss|codium|vscodium|"
    r"codex|com\.openai\.(?:codex|chatgpt)|chatgpt|openai-chatgpt|"
    r"discord|slack|spotify|"
    r"org\.gnome\..+|gnome-.+"
    r")$",
    re.IGNORECASE,
)
_CSD_EXECUTABLE = frozenset(
    {
        "chrome",
        "chromium",
        "chromium-browser",
        "electron",
        "firefox",
        "firefox-esr",
        "cursor",
        "code",
        "code-oss",
        "codium",
        "codex",
        "chatgpt",
    }
)
# Apps that never ship min/max/close themselves — always keep hyprbars.
# Defense against stale jugoo_hyprbars_csd.conf entries after class renames.
_FORCE_HYPRBARS_CLASS = frozenset(
    {
        "aidychat",
        "aidylink",
        "aidyc",
        "aidyship",
        "foot",
        "thunar",
        "xfce4-terminal",
    }
)
_CLASS_MARK = re.compile(r"^# class: (.+)$", re.MULTILINE)
SHELL_CLASS = "com.jugoo.Shell"


def client_draws_title_buttons(
    *,
    class_name: str,
    executable: str = "",
    maps: str = "",
) -> bool:
    """True when the application already has its own window buttons.

    Hyprland has no generic CSD-button capability, so use stable class/app_id
    and process metadata for applications known to draw those controls.

    ``maps`` is accepted for call-site compatibility but ignored: linking
    libadwaita does not guarantee minimize/maximize/close buttons.
    """
    del maps  # intentionally unused — see docstring
    name = (class_name or "").strip()
    if name.lower() in _FORCE_HYPRBARS_CLASS:
        return False
    if _CSD_CLASS.match(name):
        return True
    base = (executable or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return base in _CSD_EXECUTABLE


def classes_in_rules(text: str) -> set[str]:
    return {match.group(1).strip() for match in _CLASS_MARK.finditer(text or "") if match.group(1).strip()}


def render_csd_rules(classes: Iterable[str]) -> str:
    """Hyprland window rules that hide hyprbars for these classes."""
    names = sorted({name.strip() for name in classes if name and name.strip() and name.strip() != SHELL_CLASS})
    lines = [
        "# Generado por ventanas. No editar.",
        "# Aplicaciones que ya dibujan minimizar, maximizar y cerrar.",
        "",
    ]
    seen: set[str] = set()
    for name in names:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "app"
        if slug in seen:
            slug = f"{slug}-{len(seen)}"
        seen.add(slug)
        lines.append(f"# class: {name}")
        lines.append("windowrule {")
        lines.append(f"    name = jugoo-sin-barra-{slug}")
        lines.append(f"    match:class = ^({re.escape(name)})$")
        lines.append("    hyprbars:no_bar = true")
        lines.append("}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def updated_rules(previous: str, detected: Iterable[str]) -> str | None:
    """Merge detected classes; drop stale false positives from older heuristics."""
    detected_set = {
        name.strip()
        for name in detected
        if name and name.strip() and client_draws_title_buttons(class_name=name.strip())
    }
    classes = {
        name
        for name in classes_in_rules(previous)
        if name in detected_set or client_draws_title_buttons(class_name=name)
    }
    classes.update(detected_set)
    # Never hide hyprbars on apps we know lack caption buttons.
    classes = {name for name in classes if name.lower() not in _FORCE_HYPRBARS_CLASS}
    rendered = render_csd_rules(classes)
    if (previous or "").strip() == rendered.strip():
        return None
    return rendered
