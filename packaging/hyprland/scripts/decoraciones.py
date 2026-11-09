"""Decide which windows already draw their own minimize / maximize / close."""

from __future__ import annotations

import re
from collections.abc import Iterable

# Toolkits that paint caption buttons inside the client and ignore SSD.
_CSD_CLASS = re.compile(
    r"^(?:"
    r"google-chrome(?:-[\w-]+)?|chromium(?:-browser)?|brave-browser|"
    r"microsoft-edge|vivaldi|"
    r"firefox(?:-esr)?|librewolf|zen|"
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
    """
    if _CSD_CLASS.match((class_name or "").strip()):
        return True
    base = (executable or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base in _CSD_EXECUTABLE:
        return True
    return "libadwaita" in (maps or "")


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
    """Return new rule text when ``detected`` adds a class, else None."""
    classes = classes_in_rules(previous)
    classes.update(name.strip() for name in detected if name and name.strip())
    rendered = render_csd_rules(classes)
    if (previous or "").strip() == rendered.strip():
        return None
    return rendered
