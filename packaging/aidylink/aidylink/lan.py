"""LAN TCP JSON-lines transport for signed chat envelopes."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

from . import PROTOCOL
from .config import LinkConfig
from .crypto import sign_payload, verify_payload
from .messages import LinkMessage

LOGGER = logging.getLogger(__name__)


class LanTransport:
    def __init__(
        self,
        cfg: LinkConfig,
        *,
        on_message: Callable[[LinkMessage], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.on_message = on_message
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            host="0.0.0.0",
            port=self.cfg.message_port,
        )
        LOGGER.info("lan messages listening on tcp/%s", self.cfg.message_port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def send(self, host: str, port: int, message: LinkMessage) -> None:
        body = message.to_body()
        body["protocol"] = PROTOCOL
        envelope = {"body": body, "sig": sign_payload(self.cfg.team_secret, body)}
        line = (json.dumps(envelope, ensure_ascii=False) + "\n").encode("utf-8")
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=4.0,
        )
        try:
            writer.write(line)
            await writer.drain()
            # optional ack
            try:
                ack = await asyncio.wait_for(reader.readline(), timeout=2.0)
                if ack and b'"ok"' not in ack:
                    LOGGER.debug("unexpected lan ack: %s", ack[:80])
            except asyncio.TimeoutError:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not raw:
                return
            try:
                envelope = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                writer.write(b'{"ok":false,"error":"bad json"}\n')
                await writer.drain()
                return
            body = envelope.get("body") if isinstance(envelope, dict) else None
            sig = envelope.get("sig") if isinstance(envelope, dict) else None
            if not isinstance(body, dict) or body.get("protocol") != PROTOCOL:
                writer.write(b'{"ok":false,"error":"bad protocol"}\n')
                await writer.drain()
                return
            if body.get("team_id") != self.cfg.team_id:
                writer.write(b'{"ok":false,"error":"team"}\n')
                await writer.drain()
                return
            if not verify_payload(self.cfg.team_secret, body, str(sig or "")):
                writer.write(b'{"ok":false,"error":"sig"}\n')
                await writer.drain()
                return
            if body.get("type") != "chat":
                writer.write(b'{"ok":false,"error":"type"}\n')
                await writer.drain()
                return
            # Accept if addressed to us or broadcast team ("*")
            to_id = str(body.get("to_id") or "")
            if to_id not in (self.cfg.node_id, "*", ""):
                writer.write(b'{"ok":false,"error":"not for me"}\n')
                await writer.drain()
                return
            message = LinkMessage.from_body(body, via="lan")
            writer.write(b'{"ok":true}\n')
            await writer.drain()
            if self.on_message:
                self.on_message(message)
        except Exception as exc:
            LOGGER.debug("lan client error: %s", exc)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
