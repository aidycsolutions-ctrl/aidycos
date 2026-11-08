"""UDP presence beacons for AidyC-OS peers on the LAN."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Callable

from . import PROTOCOL
from .config import LinkConfig
from .crypto import sign_payload, verify_payload
from .netutil import detect_lan_ip

LOGGER = logging.getLogger(__name__)

PEER_TTL_S = 12.0
BEACON_INTERVAL_S = 2.5


@dataclass
class Peer:
    node_id: str
    display_name: str
    team_id: str
    host: str
    message_port: int
    last_seen: float
    aidychat_user_id: int | None = None

    @property
    def online(self) -> bool:
        return (time.time() - self.last_seen) <= PEER_TTL_S


class DiscoveryService:
    def __init__(
        self,
        cfg: LinkConfig,
        *,
        on_peer: Callable[[Peer], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.on_peer = on_peer
        self.peers: dict[str, Peer] = {}
        self._transport: asyncio.DatagramTransport | None = None
        self._task: asyncio.Task | None = None
        self.lan_ip = detect_lan_ip()

    def list_online(self) -> list[Peer]:
        now = time.time()
        return [
            peer
            for peer in self.peers.values()
            if (now - peer.last_seen) <= PEER_TTL_S and peer.node_id != self.cfg.node_id
        ]

    def find(self, query: str) -> Peer | None:
        q = (query or "").strip().lower()
        if not q:
            return None
        for peer in self.list_online():
            if peer.node_id.lower() == q or peer.display_name.lower() == q:
                return peer
        return None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self.lan_ip = detect_lan_ip()

        class Protocol(asyncio.DatagramProtocol):
            def __init__(self, outer: "DiscoveryService") -> None:
                self.outer = outer

            def datagram_received(self, data: bytes, addr: tuple) -> None:
                self.outer._on_datagram(data, addr[0])

        transport, _ = await loop.create_datagram_endpoint(
            lambda: Protocol(self),
            local_addr=("0.0.0.0", self.cfg.discovery_port),
            allow_broadcast=True,
        )
        self._transport = transport
        self._task = asyncio.create_task(self._beacon_loop(), name="aidylink-beacon")
        LOGGER.info("discovery listening on udp/%s", self.cfg.discovery_port)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._transport:
            self._transport.close()
            self._transport = None

    async def _beacon_loop(self) -> None:
        while True:
            try:
                self._send_beacon()
            except OSError as exc:
                LOGGER.debug("beacon send failed: %s", exc)
            await asyncio.sleep(BEACON_INTERVAL_S)

    def _send_beacon(self) -> None:
        if not self._transport:
            return
        self.lan_ip = detect_lan_ip()
        body = {
            "protocol": PROTOCOL,
            "type": "presence",
            "node_id": self.cfg.node_id,
            "display_name": self.cfg.display_name,
            "team_id": self.cfg.team_id,
            "message_port": self.cfg.message_port,
            "host": self.lan_ip,
            "ts": int(time.time()),
        }
        if self.cfg.cloud.enabled and self.cfg.cloud.peer_user_ids.get("self"):
            body["aidychat_user_id"] = self.cfg.cloud.peer_user_ids["self"]
        envelope = {"body": body, "sig": sign_payload(self.cfg.team_secret, body)}
        payload = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        self._transport.sendto(payload, ("255.255.255.255", self.cfg.discovery_port))

    def _on_datagram(self, data: bytes, host: str) -> None:
        try:
            envelope = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return
        if not isinstance(envelope, dict):
            return
        body = envelope.get("body")
        sig = envelope.get("sig")
        if not isinstance(body, dict):
            return
        if body.get("protocol") != PROTOCOL or body.get("type") != "presence":
            return
        if body.get("team_id") != self.cfg.team_id:
            return
        if not verify_payload(self.cfg.team_secret, body, str(sig or "")):
            LOGGER.debug("ignored presence with bad signature from %s", host)
            return
        node_id = str(body.get("node_id") or "")
        if not node_id or node_id == self.cfg.node_id:
            return
        peer = Peer(
            node_id=node_id,
            display_name=str(body.get("display_name") or node_id[:8]),
            team_id=str(body.get("team_id") or ""),
            host=str(body.get("host") or host),
            message_port=int(body.get("message_port") or self.cfg.message_port),
            last_seen=time.time(),
            aidychat_user_id=(
                int(body["aidychat_user_id"])
                if body.get("aidychat_user_id") is not None
                else None
            ),
        )
        self.peers[node_id] = peer
        if self.on_peer:
            self.on_peer(peer)
