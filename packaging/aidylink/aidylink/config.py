"""Load / save AidyLink configuration."""

from __future__ import annotations

import json
import os
import secrets
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .paths import config_path


@dataclass
class CloudConfig:
    enabled: bool = False
    base_url: str = ""
    bearer_token: str = ""
    poll_seconds: float = 4.0
    turn_server: str = ""
    # local display name / peer id → AidyChat numeric user id (when known)
    peer_user_ids: dict[str, int] = field(default_factory=dict)


@dataclass
class LinkConfig:
    node_id: str
    display_name: str
    team_id: str
    team_secret: str
    discovery_port: int = 47832
    message_port: int = 47833
    cloud: CloudConfig = field(default_factory=CloudConfig)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LinkConfig":
        cloud_raw = raw.get("cloud") or {}
        cloud = CloudConfig(
            enabled=bool(cloud_raw.get("enabled")),
            base_url=str(cloud_raw.get("base_url") or "").rstrip("/"),
            bearer_token=str(cloud_raw.get("bearer_token") or ""),
            poll_seconds=float(cloud_raw.get("poll_seconds") or 4.0),
            turn_server=str(cloud_raw.get("turn_server") or "").strip(),
            peer_user_ids={
                str(k): int(v) for k, v in (cloud_raw.get("peer_user_ids") or {}).items()
            },
        )
        return cls(
            node_id=str(raw["node_id"]),
            display_name=str(raw.get("display_name") or "AidyC-OS"),
            team_id=str(raw.get("team_id") or "default"),
            team_secret=str(raw.get("team_secret") or ""),
            discovery_port=int(raw.get("discovery_port") or 47832),
            message_port=int(raw.get("message_port") or 47833),
            cloud=cloud,
        )


def load_config(path: Path | None = None) -> LinkConfig | None:
    target = path or config_path()
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or "node_id" not in raw:
        return None
    return LinkConfig.from_dict(raw)


def save_config(cfg: LinkConfig, path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    payload = json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False) + "\n"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)
    os.replace(tmp, target)
    return target


def init_config(
    *,
    display_name: str,
    team_id: str,
    team_secret: str | None = None,
    path: Path | None = None,
) -> LinkConfig:
    existing = load_config(path)
    secret = (team_secret or "").strip() or (existing.team_secret if existing else "") or secrets.token_urlsafe(24)
    node_id = existing.node_id if existing else str(uuid.uuid4())
    cloud = existing.cloud if existing else CloudConfig()
    cfg = LinkConfig(
        node_id=node_id,
        display_name=display_name.strip() or "AidyC-OS",
        team_id=team_id.strip() or "default",
        team_secret=secret,
        cloud=cloud,
    )
    save_config(cfg, path)
    return cfg
