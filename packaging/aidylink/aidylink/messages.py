"""Message envelope shared by LAN and cloud paths."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Literal

Via = Literal["lan", "cloud", "local"]


@dataclass
class LinkMessage:
    msg_id: str
    from_id: str
    from_name: str
    to_id: str
    text: str
    ts: float
    via: Via = "lan"
    team_id: str = ""

    @classmethod
    def create(
        cls,
        *,
        from_id: str,
        from_name: str,
        to_id: str,
        text: str,
        team_id: str,
        via: Via = "lan",
    ) -> "LinkMessage":
        return cls(
            msg_id=str(uuid.uuid4()),
            from_id=from_id,
            from_name=from_name,
            to_id=to_id,
            text=text.strip(),
            ts=time.time(),
            via=via,
            team_id=team_id,
        )

    def to_body(self) -> dict[str, Any]:
        return {
            "type": "chat",
            "msg_id": self.msg_id,
            "from_id": self.from_id,
            "from_name": self.from_name,
            "to_id": self.to_id,
            "text": self.text,
            "ts": self.ts,
            "team_id": self.team_id,
        }

    @classmethod
    def from_body(cls, body: dict[str, Any], *, via: Via) -> "LinkMessage":
        return cls(
            msg_id=str(body.get("msg_id") or uuid.uuid4()),
            from_id=str(body.get("from_id") or ""),
            from_name=str(body.get("from_name") or ""),
            to_id=str(body.get("to_id") or ""),
            text=str(body.get("text") or ""),
            ts=float(body.get("ts") or time.time()),
            via=via,
            team_id=str(body.get("team_id") or ""),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
