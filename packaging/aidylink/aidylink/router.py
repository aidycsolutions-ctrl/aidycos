"""Prefer LAN delivery; fall back to AidyChat cloud."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .cloud import AidyChatBridge
from .config import LinkConfig
from .discovery import DiscoveryService, Peer
from .lan import LanTransport
from .messages import LinkMessage
from .netutil import detect_lan_ip, resolve_lan_endpoint

LOGGER = logging.getLogger(__name__)

Route = Literal["lan", "cloud", "failed"]


@dataclass
class SendResult:
    route: Route
    detail: str = ""
    message: LinkMessage | None = None


class MessageRouter:
    def __init__(
        self,
        cfg: LinkConfig,
        discovery: DiscoveryService,
        lan: LanTransport,
        cloud: AidyChatBridge,
    ) -> None:
        self.cfg = cfg
        self.discovery = discovery
        self.lan = lan
        self.cloud = cloud

    async def send_direct(
        self,
        *,
        host: str,
        port: int,
        text: str,
        to_id: str = "*",
        message: LinkMessage | None = None,
    ) -> SendResult:
        """Send to an explicit LAN host (useful for QEMU NAT / no discovery)."""
        if message is None:
            text = (text or "").strip()
            if not text:
                return SendResult(route="failed", detail="mensaje vacío")
            message = LinkMessage.create(
                from_id=self.cfg.node_id,
                from_name=self.cfg.display_name,
                to_id=to_id or "*",
                text=text,
                team_id=self.cfg.team_id,
                via="lan",
            )
        local_ip = self.discovery.lan_ip or detect_lan_ip()
        dest_host, dest_port = resolve_lan_endpoint(host, port, local_ip=local_ip)
        try:
            await self.lan.send(dest_host, dest_port, message)
        except Exception as exc:
            err = str(exc).strip() or exc.__class__.__name__
            hint = ""
            if host.startswith("10.0.2.") and dest_host == "127.0.0.1":
                hint = " (vía hostfwd QEMU)"
            return SendResult(
                route="failed",
                detail=f"LAN directo {dest_host}:{dest_port}{hint}: {err}",
            )
        detail = f"{dest_host}:{dest_port}"
        if (dest_host, dest_port) != (host, int(port)):
            detail += f" (peer {host}:{port} vía QEMU hostfwd)"
        return SendResult(route="lan", detail=detail, message=message)

    async def send_text(self, target: str, text: str) -> SendResult:
        text = (text or "").strip()
        if not text:
            return SendResult(route="failed", detail="mensaje vacío")
        message = LinkMessage.create(
            from_id=self.cfg.node_id,
            from_name=self.cfg.display_name,
            to_id="",  # filled once peer is resolved
            text=text,
            team_id=self.cfg.team_id,
            via="lan",
        )
        return await self.send_message(target, message)

    async def send_file(self, target: str, path: Path, *, caption: str = "") -> SendResult:
        peer = self.discovery.find(target)
        to_id = peer.node_id if peer else target
        try:
            message = LinkMessage.from_file(
                Path(path),
                from_id=self.cfg.node_id,
                from_name=self.cfg.display_name,
                to_id=to_id or "*",
                team_id=self.cfg.team_id,
                caption=caption,
                via="lan",
            )
        except (OSError, ValueError) as exc:
            return SendResult(route="failed", detail=str(exc))
        return await self.send_message(target, message)

    async def send_message(self, target: str, message: LinkMessage) -> SendResult:
        peer = self.discovery.find(target)
        if peer and peer.online:
            message.to_id = peer.node_id
            return await self._send_lan_message(peer, message)

        text = message.display_text()
        mapped = self.cfg.cloud.peer_user_ids.get(target) or self.cfg.cloud.peer_user_ids.get(
            target.lower()
        )
        if mapped is None and peer and peer.aidychat_user_id:
            mapped = peer.aidychat_user_id

        if mapped is not None and self.cloud.enabled and message.kind == "text":
            return await self._send_cloud(int(mapped), target, text)

        if peer is None and self.cloud.enabled:
            return SendResult(
                route="failed",
                detail=(
                    f"No hay peer LAN «{target}» y no hay mapeo "
                    f"cloud.peer_user_ids['{target}']. Usa `aidylink peers` "
                    "o configura el user id de AidyChat."
                ),
            )

        if peer is not None and not peer.online:
            return SendResult(
                route="failed",
                detail=f"{peer.display_name} está offline en LAN",
            )

        return SendResult(route="failed", detail=f"destinatario desconocido: {target}")

    async def _send_lan_message(self, peer: Peer, message: LinkMessage) -> SendResult:
        local_ip = self.discovery.lan_ip or detect_lan_ip()
        dest_host, dest_port = resolve_lan_endpoint(
            peer.host, peer.message_port, local_ip=local_ip
        )
        try:
            await self.lan.send(dest_host, dest_port, message)
        except Exception as exc:
            LOGGER.info("lan send failed (%s); trying cloud", exc)
            if message.kind == "text":
                if peer.aidychat_user_id and self.cloud.enabled:
                    return await self._send_cloud(
                        peer.aidychat_user_id, peer.display_name, message.text
                    )
                mapped = self.cfg.cloud.peer_user_ids.get(peer.display_name)
                if mapped and self.cloud.enabled:
                    return await self._send_cloud(int(mapped), peer.display_name, message.text)
            err = str(exc).strip() or exc.__class__.__name__
            return SendResult(
                route="failed",
                detail=f"LAN falló {dest_host}:{dest_port}: {err}",
            )
        detail = peer.display_name
        if (dest_host, dest_port) != (peer.host, peer.message_port):
            detail = f"{peer.display_name} vía {dest_host}:{dest_port}"
        return SendResult(route="lan", detail=detail, message=message)

    async def _send_cloud(self, user_id: int, label: str, text: str) -> SendResult:
        import asyncio

        message = LinkMessage.create(
            from_id=self.cfg.node_id,
            from_name=self.cfg.display_name,
            to_id=f"aidychat:{user_id}",
            text=text,
            team_id=self.cfg.team_id,
            via="cloud",
        )
        try:
            await asyncio.to_thread(self.cloud.send_text, user_id, text)
        except Exception as exc:
            return SendResult(route="failed", detail=f"cloud: {exc}")
        return SendResult(route="cloud", detail=label, message=message)
