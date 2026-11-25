"""Register XDG-installed user icons with GTK's default icon theme."""
from __future__ import annotations

import os
from pathlib import Path


def append_user_icon_search_paths(icon_theme, *, data_home: Path | None = None, home: Path | None = None) -> tuple[Path, ...]:
    """Add existing per-user icon directories so GTK can resolve desktop Icon names."""
    user_home = Path(home or Path.home()).expanduser()
    xdg_home = Path(data_home or os.environ.get("XDG_DATA_HOME") or (user_home / ".local/share")).expanduser()
    candidates = (xdg_home / "icons", user_home / ".icons")
    existing = {str(Path(path).expanduser().resolve()) for path in icon_theme.get_search_path()}
    added = []
    for candidate in candidates:
        path = candidate.resolve()
        if not path.is_dir() or str(path) in existing:
            continue
        icon_theme.append_search_path(str(path))
        existing.add(str(path))
        added.append(path)
    return tuple(added)
