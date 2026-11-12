"""Persisted favorites and last-used repo for AidyShip."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import config_path


@dataclass
class ShipConfig:
    favorites: list[str] = field(default_factory=list)
    last_repo: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "favorites": list(self.favorites),
            "last_repo": self.last_repo,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ShipConfig:
        raw = data or {}
        favorites: list[str] = []
        for item in raw.get("favorites") or []:
            text = str(item).strip()
            if text and text not in favorites:
                favorites.append(text)
        return cls(
            favorites=favorites,
            last_repo=str(raw.get("last_repo") or "").strip(),
        )


def load_config() -> ShipConfig:
    path = config_path()
    if not path.is_file():
        return ShipConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ShipConfig()
    if not isinstance(data, dict):
        return ShipConfig()
    return ShipConfig.from_dict(data)


def save_config(cfg: ShipConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def add_favorite(cfg: ShipConfig, repo: Path | str) -> ShipConfig:
    resolved = str(Path(repo).expanduser().resolve())
    favorites = [resolved] + [item for item in cfg.favorites if item != resolved]
    cfg.favorites = favorites[:24]
    cfg.last_repo = resolved
    save_config(cfg)
    return cfg


def remove_favorite(cfg: ShipConfig, repo: Path | str) -> ShipConfig:
    resolved = str(Path(repo).expanduser().resolve())
    cfg.favorites = [item for item in cfg.favorites if item != resolved]
    if cfg.last_repo == resolved:
        cfg.last_repo = cfg.favorites[0] if cfg.favorites else ""
    save_config(cfg)
    return cfg
