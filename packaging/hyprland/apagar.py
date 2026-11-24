"""Super+Alt+F4 shuts the machine down after Enter confirms."""

from __future__ import annotations

import re

SHUTDOWN_BIND = (
    "bind = SUPER ALT, F4, exec, ~/.config/hypr/scripts/confirmar-apagar"
)
SHUTDOWN_COMMENT = "# Super+Alt+F4: apagar. Enter confirma, Escape cancela."
RULE_BLOCK = """windowrule {
    name = confirmar-apagar
    match:class = ^(org\\.aidycos\\.Apagar)$
    float = true
    center = true
}
"""

_BIND_RE = re.compile(
    r"(?m)^[ \t]*bind[ \t]*=[ \t]*SUPER ALT,[ \t]*F4,[^\n]*\n?"
)
_COMMENT_RE = re.compile(
    r"(?m)^[ \t]*# Super\+Alt\+F4: apagar\. Enter confirma, Escape cancela\.[ \t]*\n?"
)
_RULE_RE = re.compile(
    r"(?m)^[ \t]*windowrule[ \t]*\{[^{}]*\bname[ \t]*=[ \t]*confirmar-apagar\b[^{}]*\}[ \t]*\n?"
)


def has_bind(text: str) -> bool:
    return bool(_BIND_RE.search(text))


def has_rule(text: str) -> bool:
    return bool(_RULE_RE.search(text))


def ensure_shutdown(hyprland: str, aidycos: str) -> tuple[str, str]:
    """Leave exactly one shutdown bind and one centering rule.

    New machines get both in aidycos.conf. A bind already present in
    hyprland.conf is kept, so a second copy is not added.
    """
    hyprland, aidycos = _ensure_once(
        hyprland,
        aidycos,
        present=has_bind,
        remove=_drop_bind,
        addition=SHUTDOWN_COMMENT + "\n" + SHUTDOWN_BIND + "\n",
    )
    hyprland, aidycos = _ensure_once(
        hyprland,
        aidycos,
        present=has_rule,
        remove=lambda text: _RULE_RE.sub("", text),
        addition=RULE_BLOCK,
    )
    return hyprland, aidycos


def strip_shutdown(text: str) -> str:
    """Drop the shortcut, its comment, and the centering rule."""
    text = _drop_bind(text)
    return _RULE_RE.sub("", text)


def _drop_bind(text: str) -> str:
    text = _BIND_RE.sub("", text)
    return _COMMENT_RE.sub("", text)


def _ensure_once(hyprland: str, aidycos: str, *, present, remove, addition: str) -> tuple[str, str]:
    in_hyprland = present(hyprland)
    in_aidycos = present(aidycos)
    if in_hyprland and in_aidycos:
        return remove(hyprland), aidycos
    if in_hyprland or in_aidycos:
        return hyprland, aidycos
    return hyprland, _append(aidycos, addition)


def _append(text: str, addition: str) -> str:
    if text and not text.endswith("\n"):
        text += "\n"
    if text and not text.endswith("\n\n"):
        text += "\n"
    return text + addition
