"""Hyprland binds for system volume and screen brightness."""

from __future__ import annotations

import re

MARKER_BEGIN = "# >>> aidycos-medios begin"
MARKER_END = "# >>> aidycos-medios end"

# Fn+Fx is translated by the keyboard into XF86* keys. Super+Fx covers
# keyboards that have no Fn key.
MEDIA_BINDS: tuple[str, ...] = (
    "bindel = , XF86AudioRaiseVolume, exec, ~/.local/bin/aidycos-medios volume-up",
    "bindel = , XF86AudioLowerVolume, exec, ~/.local/bin/aidycos-medios volume-down",
    "bindl = , XF86AudioMute, exec, ~/.local/bin/aidycos-medios mute",
    "bindel = , XF86MonBrightnessUp, exec, ~/.local/bin/aidycos-medios brightness-up",
    "bindel = , XF86MonBrightnessDown, exec, ~/.local/bin/aidycos-medios brightness-down",
    "bindl = SUPER, F1, exec, ~/.local/bin/aidycos-medios mute",
    "bindel = SUPER, F2, exec, ~/.local/bin/aidycos-medios volume-down",
    "bindel = SUPER, F3, exec, ~/.local/bin/aidycos-medios volume-up",
    "bindel = SUPER, F4, exec, ~/.local/bin/aidycos-medios brightness-down",
    "bindel = SUPER, F5, exec, ~/.local/bin/aidycos-medios brightness-up",
)

_BLOCK_RE = re.compile(
    re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END) + r"\n?",
    re.DOTALL,
)
# Super+F1/F2/F3 used to change the music player, which would also fire.
_PLAYER_VOLUME_RE = re.compile(
    r"(?m)^[ \t]*bind\w*[ \t]*=[ \t]*SUPER,[ \t]*F[123],[ \t]*exec,[ \t]*"
    r"jugoo action (?:musicVolumeUp|musicVolumeDown|musicMuteToggle)[ \t]*\n?"
)


def render_block() -> str:
    lines = [
        MARKER_BEGIN,
        "# Volumen del sistema y brillo. Fn+F1…F5 llega como XF86*; sin Fn, Super+F1…F5.",
        *MEDIA_BINDS,
        MARKER_END,
    ]
    return "\n".join(lines) + "\n"


def retire_player_volume_binds(text: str) -> str:
    """Drop player-volume binds on Super+F1/F2/F3 so they do not stack."""
    return _PLAYER_VOLUME_RE.sub("", text)


def ensure_media_binds(text: str) -> str:
    """Insert or replace the media-key block. Idempotent."""
    text = retire_player_volume_binds(text)
    block = render_block()
    if _BLOCK_RE.search(text):
        return _BLOCK_RE.sub(block, text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    if text and not text.endswith("\n\n"):
        text += "\n"
    return text + block
