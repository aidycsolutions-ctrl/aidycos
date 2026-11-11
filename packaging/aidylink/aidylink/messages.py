"""Message envelope shared by LAN and cloud paths."""

from __future__ import annotations

import base64
import mimetypes
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Via = Literal["lan", "cloud", "local"]

# Keep LAN JSON-lines transfers comfortable on typical Wi‑Fi.
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024


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
    kind: str = "text"  # text | image | file
    filename: str = ""
    mime: str = ""
    media_b64: str = ""  # transit only; cleared before inbox persistence when possible
    media_path: str = ""  # local path after save

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
        kind: str = "text",
        filename: str = "",
        mime: str = "",
        media_b64: str = "",
        media_path: str = "",
    ) -> "LinkMessage":
        return cls(
            msg_id=str(uuid.uuid4()),
            from_id=from_id,
            from_name=from_name,
            to_id=to_id,
            text=(text or "").strip(),
            ts=time.time(),
            via=via,
            team_id=team_id,
            kind=kind or "text",
            filename=filename or "",
            mime=mime or "",
            media_b64=media_b64 or "",
            media_path=media_path or "",
        )

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        from_id: str,
        from_name: str,
        to_id: str,
        team_id: str,
        caption: str = "",
        via: Via = "lan",
    ) -> "LinkMessage":
        path = Path(path)
        data = path.read_bytes()
        if not data:
            raise ValueError("El archivo está vacío")
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError("El archivo supera el límite de 15 MB para red local")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        kind = "image" if mime.startswith("image/") else "file"
        return cls.create(
            from_id=from_id,
            from_name=from_name,
            to_id=to_id,
            text=caption,
            team_id=team_id,
            via=via,
            kind=kind,
            filename=path.name,
            mime=mime,
            media_b64=base64.b64encode(data).decode("ascii"),
            media_path=str(path.resolve()),
        )

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": "chat",
            "msg_id": self.msg_id,
            "from_id": self.from_id,
            "from_name": self.from_name,
            "to_id": self.to_id,
            "text": self.text,
            "ts": self.ts,
            "team_id": self.team_id,
            "kind": self.kind,
            "filename": self.filename,
            "mime": self.mime,
        }
        if self.media_b64:
            body["media_b64"] = self.media_b64
        return body

    @classmethod
    def from_body(cls, body: dict[str, Any], *, via: Via) -> "LinkMessage":
        kind = str(body.get("kind") or "text")
        mime = str(body.get("mime") or "")
        filename = str(body.get("filename") or "")
        media_b64 = str(body.get("media_b64") or "")
        if media_b64 and kind == "text":
            kind = "image" if mime.startswith("image/") else "file"
        return cls(
            msg_id=str(body.get("msg_id") or uuid.uuid4()),
            from_id=str(body.get("from_id") or ""),
            from_name=str(body.get("from_name") or ""),
            to_id=str(body.get("to_id") or ""),
            text=str(body.get("text") or ""),
            ts=float(body.get("ts") or time.time()),
            via=via,
            team_id=str(body.get("team_id") or ""),
            kind=kind,
            filename=filename,
            mime=mime,
            media_b64=media_b64,
            media_path=str(body.get("media_path") or ""),
        )

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Never dump multi‑MB payloads into the inbox log.
        if data.get("media_b64") and data.get("media_path"):
            data["media_b64"] = ""
        elif data.get("media_b64") and len(data["media_b64"]) > 256:
            # Keep a marker so older UIs know there was media.
            data["has_media"] = True
            data["media_b64"] = ""
        return data

    def display_text(self) -> str:
        if self.text:
            return self.text
        if self.kind == "image":
            return self.filename or "Imagen"
        if self.kind == "file":
            return self.filename or "Archivo"
        return ""
