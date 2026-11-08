"""XDG paths for AidyLink state."""

from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / "aidylink"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    path = Path(base) / "aidylink"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        path = Path(base)
    else:
        path = Path("/tmp") / f"aidylink-{os.getuid()}"
        path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def control_socket_path() -> Path:
    return runtime_dir() / "aidylink.sock"
