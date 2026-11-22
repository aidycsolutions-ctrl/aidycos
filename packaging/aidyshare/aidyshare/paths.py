"""XDG paths for AidyShare."""

from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / "aidyshare"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def session_path() -> Path:
    return config_dir() / "session.json"
