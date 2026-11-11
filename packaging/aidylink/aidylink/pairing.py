"""LAN pairing — durable group code + optional short-lived PIN for mobile QR."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

from . import PROTOCOL
from .config import LinkConfig
from .netutil import detect_lan_ip, lan_subnet_hosts

LOGGER = logging.getLogger(__name__)

PAIR_TTL_S = 180.0
PAIR_CONNECT_TIMEOUT_S = 1.5
PAIR_SCAN_CONCURRENCY = 64


@dataclass
class PairingSession:
    pin: str
    expires_at: float

    @property
    def active(self) -> bool:
        return time.time() <= self.expires_at


def generate_pin() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def group_code_for(cfg: LinkConfig) -> str:
    """Stable 6-digit code for this PC's group. Survives Wi‑Fi changes.

    Anyone who enters this code while on the same LAN receives the current
    team_id/team_secret. No need to open a temporary host session.
    """
    material = f"aidylink-group-v1:{cfg.team_id}:{cfg.team_secret}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{int(digest[:8], 16) % 1_000_000:06d}"


class PairingService:
    def __init__(self, cfg: LinkConfig) -> None:
        self.cfg = cfg
        self._session: PairingSession | None = None
        self._paired_at: float = 0.0

    def group_code(self) -> str:
        return group_code_for(self.cfg)

    def start_host(self) -> dict[str, Any]:
        """Start a short-lived PIN (mainly for mobile QR). PC join uses group_code."""
        pin = generate_pin()
        self._paired_at = 0.0
        self._session = PairingSession(pin=pin, expires_at=time.time() + PAIR_TTL_S)
        code = self.group_code()
        return {
            "ok": True,
            "pin": pin,
            "group_code": code,
            "expires_in": int(PAIR_TTL_S),
            "display_name": self.cfg.display_name,
            "team_id": self.cfg.team_id,
        }

    def stop(self) -> None:
        self._session = None

    def status(self) -> dict[str, Any]:
        session = self._session
        code = self.group_code()
        if session and session.active:
            return {
                "ok": True,
                "active": True,
                "paired": False,
                "pin": session.pin,
                "group_code": code,
                "expires_in": max(0, int(session.expires_at - time.time())),
                "display_name": self.cfg.display_name,
            }
        self._session = None
        paired = self._paired_at > 0 and (time.time() - self._paired_at) < 15
        return {
            "ok": True,
            "active": False,
            "paired": paired,
            "group_code": code,
        }

    def verify_pin(self, pin: str) -> bool:
        """True for active temp PIN or the permanent group code (does not consume)."""
        candidate = str(pin or "").strip()
        if not candidate:
            return False
        if secrets.compare_digest(candidate, self.group_code()):
            return True
        session = self._session
        if not session or not session.active:
            return False
        return secrets.compare_digest(candidate, session.pin)

    def _grant_body(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL,
            "type": "pair_grant",
            "team_id": self.cfg.team_id,
            "team_secret": self.cfg.team_secret,
            "host_name": self.cfg.display_name,
            "host_node_id": self.cfg.node_id,
            "group_code": self.group_code(),
            "ts": int(time.time()),
        }

    def handle_request(self, body: dict[str, Any]) -> dict[str, Any] | None:
        """Accept temporary PIN (consumes) or permanent group_code (reusable)."""
        pin = str(body.get("pin") or body.get("group_code") or "").strip()
        if not pin:
            return {"ok": False, "error": "pin"}

        # Permanent group code: always available, never expires, Wi‑Fi-proof.
        if secrets.compare_digest(pin, self.group_code()):
            self._paired_at = time.time()
            return {"ok": True, "body": self._grant_body()}

        session = self._session
        if session and session.active and secrets.compare_digest(pin, session.pin):
            grant = self._grant_body()
            # Temporary mobile PIN is one-shot.
            self._session = None
            self._paired_at = time.time()
            return {"ok": True, "body": grant}
        return {"ok": False, "error": "pin"}

    async def join(
        self,
        pin: str,
        *,
        hosts: list[str] | None = None,
        message_port: int | None = None,
    ) -> dict[str, Any]:
        pin = (pin or "").strip()
        if not pin.isdigit() or len(pin) != 6:
            return {"ok": False, "error": "El código debe tener 6 dígitos"}
        # Same code as ours → already in the group.
        if secrets.compare_digest(pin, self.group_code()):
            return {
                "ok": True,
                "team_id": self.cfg.team_id,
                "team_secret": self.cfg.team_secret,
                "host": "local",
                "host_name": self.cfg.display_name,
                "already_member": True,
            }

        port = int(message_port or self.cfg.message_port)
        lan_ip = detect_lan_ip()
        targets: list[str] = []
        seen: set[str] = set()
        for host in hosts or []:
            host = (host or "").strip()
            if host and host != lan_ip and host not in seen:
                seen.add(host)
                targets.append(host)
        for host in lan_subnet_hosts(exclude=lan_ip):
            if host not in seen:
                seen.add(host)
                targets.append(host)
        if not targets:
            return {
                "ok": False,
                "error": (
                    "No hay equipos en esta Wi‑Fi. Conéctate a la misma red "
                    "que el otro PC e inténtalo de nuevo."
                ),
            }

        body = {
            "protocol": PROTOCOL,
            "type": "pair_request",
            "pin": pin,
            "group_code": pin,
            "node_id": self.cfg.node_id,
            "display_name": self.cfg.display_name,
            "ts": int(time.time()),
        }
        line = (json.dumps({"body": body}, ensure_ascii=False) + "\n").encode("utf-8")
        sem = asyncio.Semaphore(PAIR_SCAN_CONCURRENCY)
        found: dict[str, Any] = {}

        async def _try(host: str) -> None:
            if found:
                return
            async with sem:
                if found:
                    return
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(host, port),
                        timeout=PAIR_CONNECT_TIMEOUT_S,
                    )
                except (OSError, asyncio.TimeoutError):
                    return
                try:
                    writer.write(line)
                    await writer.drain()
                    raw = await asyncio.wait_for(reader.readline(), timeout=2.0)
                except (OSError, asyncio.TimeoutError):
                    return
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
                if found or not raw:
                    return
                try:
                    reply = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    return
                if not isinstance(reply, dict) or not reply.get("ok"):
                    return
                grant = reply.get("body")
                if not isinstance(grant, dict) or grant.get("type") != "pair_grant":
                    return
                team_id = str(grant.get("team_id") or "").strip()
                team_secret = str(grant.get("team_secret") or "").strip()
                if not team_id or not team_secret:
                    return
                found.update(
                    {
                        "ok": True,
                        "team_id": team_id,
                        "team_secret": team_secret,
                        "host": host,
                        "host_name": str(grant.get("host_name") or host),
                    }
                )

        await asyncio.gather(*(_try(host) for host in targets))
        if found:
            return found
        return {
            "ok": False,
            "error": (
                "Nadie aceptó ese código en esta Wi‑Fi. En el otro PC abre "
                "Emparejar y mira su código de grupo (no caduca). "
                "Ambos deben estar en la misma red."
            ),
        }
