"""UDP presence beacons + TCP subnet fallback for AidyC-OS peers on the LAN."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import PROTOCOL
from .config import LinkConfig
from .crypto import sign_payload, verify_payload
from .netutil import detect_lan_ip, lan_broadcast_addresses, lan_subnet_hosts
from .paths import data_dir

LOGGER = logging.getLogger(__name__)

PEER_TTL_S = 15.0
BEACON_INTERVAL_S = 2.5
TCP_SCAN_INTERVAL_S = 6.0
TCP_CONNECT_TIMEOUT_S = 1.2
TCP_SCAN_CONCURRENCY = 64
MISMATCH_TTL_S = 180.0
KNOWN_HOSTS_MAX = 64


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


@dataclass
class MismatchHint:
    host: str
    reason: str
    last_seen: float
    display_name: str = ""


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
        self.mismatches: dict[str, MismatchHint] = {}
        self._known_hosts: dict[str, float] = {}
        self._known_path = data_dir() / "known_hosts.json"
        self._transport: asyncio.DatagramTransport | None = None
        self._beacon_task: asyncio.Task | None = None
        self._tcp_task: asyncio.Task | None = None
        self.lan_ip = detect_lan_ip()
        self._load_known_hosts()

    def list_online(self) -> list[Peer]:
        now = time.time()
        return [
            peer
            for peer in self.peers.values()
            if (now - peer.last_seen) <= PEER_TTL_S and peer.node_id != self.cfg.node_id
        ]

    def list_mismatches(self) -> list[MismatchHint]:
        now = time.time()
        return [
            hint
            for hint in self.mismatches.values()
            if (now - hint.last_seen) <= MISMATCH_TTL_S
        ]

    def find(self, query: str) -> Peer | None:
        q = (query or "").strip().lower()
        if not q:
            return None
        for peer in self.list_online():
            if peer.node_id.lower() == q or peer.display_name.lower() == q:
                return peer
        return None

    def presence_body(self) -> dict[str, Any]:
        self.lan_ip = detect_lan_ip()
        body: dict[str, Any] = {
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
        return body

    def accept_presence(self, body: dict[str, Any], remote_host: str) -> Peer | None:
        """Validate and remember a presence body (UDP beacon or TCP hello/reply)."""
        if not isinstance(body, dict):
            return None
        if body.get("protocol") != PROTOCOL:
            return None
        if body.get("type") not in ("presence", "presence_hello"):
            return None
        if body.get("team_id") != self.cfg.team_id:
            LOGGER.debug(
                "ignored presence team mismatch from %s (got %r)",
                remote_host,
                body.get("team_id"),
            )
            return None
        node_id = str(body.get("node_id") or "")
        if not node_id or node_id == self.cfg.node_id:
            return None
        peer = Peer(
            node_id=node_id,
            display_name=str(body.get("display_name") or node_id[:8]),
            team_id=str(body.get("team_id") or ""),
            host=str(body.get("host") or remote_host),
            message_port=int(body.get("message_port") or self.cfg.message_port),
            last_seen=time.time(),
            aidychat_user_id=(
                int(body["aidychat_user_id"])
                if body.get("aidychat_user_id") is not None
                else None
            ),
        )
        self.peers[node_id] = peer
        self.mismatches.pop(remote_host, None)
        self.mismatches.pop(peer.host, None)
        self.remember_host(peer.host or remote_host)
        if self.on_peer:
            self.on_peer(peer)
        return peer

    def _load_known_hosts(self) -> None:
        if not self._known_path.is_file():
            return
        try:
            raw = json.loads(self._known_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        hosts = raw.get("hosts") if isinstance(raw, dict) else None
        if not isinstance(hosts, dict):
            return
        now = time.time()
        for host, seen in hosts.items():
            host = str(host or "").strip()
            if not host:
                continue
            try:
                ts = float(seen)
            except (TypeError, ValueError):
                ts = now
            self._known_hosts[host] = ts

    def _save_known_hosts(self) -> None:
        items = sorted(self._known_hosts.items(), key=lambda kv: kv[1], reverse=True)
        trimmed = dict(items[:KNOWN_HOSTS_MAX])
        self._known_hosts = trimmed
        try:
            self._known_path.parent.mkdir(parents=True, exist_ok=True)
            self._known_path.write_text(
                json.dumps({"hosts": trimmed}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            LOGGER.debug("known_hosts save failed: %s", exc)

    def remember_host(self, host: str) -> None:
        host = (host or "").strip()
        if not host or host == self.lan_ip or host.startswith("127."):
            return
        self._known_hosts[host] = time.time()
        self._save_known_hosts()

    def _note_mismatch(
        self,
        host: str,
        reason: str,
        *,
        display_name: str = "",
    ) -> None:
        host = (host or "").strip()
        if not host or host == self.lan_ip:
            return
        previous = self.mismatches.get(host)
        name = (display_name or "").strip() or (previous.display_name if previous else "")
        self.mismatches[host] = MismatchHint(
            host=host,
            reason=reason,
            last_seen=time.time(),
            display_name=name,
        )
        self.remember_host(host)

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
        self._beacon_task = asyncio.create_task(self._beacon_loop(), name="aidylink-beacon")
        self._tcp_task = asyncio.create_task(self._tcp_scan_loop(), name="aidylink-tcp-scan")
        LOGGER.info(
            "discovery listening on udp/%s (tcp fallback on %s)",
            self.cfg.discovery_port,
            self.cfg.message_port,
        )

    async def stop(self) -> None:
        for task in (self._beacon_task, self._tcp_task):
            if not task:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._beacon_task = None
        self._tcp_task = None
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
        body = self.presence_body()
        envelope = {"body": body, "sig": sign_payload(self.cfg.team_secret, body)}
        payload = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        for broadcast in lan_broadcast_addresses():
            try:
                self._transport.sendto(payload, (broadcast, self.cfg.discovery_port))
            except OSError as exc:
                LOGGER.debug("beacon send to %s failed: %s", broadcast, exc)

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
        if body.get("type") != "presence":
            return
        display_name = str(body.get("display_name") or "")
        if body.get("team_id") != self.cfg.team_id:
            self._note_mismatch(host, "team", display_name=display_name)
            return
        if not verify_payload(self.cfg.team_secret, body, str(sig or "")):
            LOGGER.debug("ignored presence with bad signature from %s", host)
            self._note_mismatch(host, "sig", display_name=display_name)
            return
        self.accept_presence(body, host)

    async def _tcp_scan_loop(self) -> None:
        await asyncio.sleep(0.8)
        while True:
            try:
                await self._scan_subnet_tcp()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.debug("tcp discovery scan failed: %s", exc)
            await asyncio.sleep(TCP_SCAN_INTERVAL_S)

    async def _port_open(self, host: str) -> bool:
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, self.cfg.message_port),
                timeout=TCP_CONNECT_TIMEOUT_S,
            )
        except (OSError, asyncio.TimeoutError):
            return False
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True

    async def _scan_subnet_tcp(self) -> None:
        self.lan_ip = detect_lan_ip()
        targets = list(lan_subnet_hosts(exclude=self.lan_ip))
        for peer in self.list_online():
            if peer.host and peer.host not in targets and peer.host != self.lan_ip:
                targets.insert(0, peer.host)
        for hint in self.list_mismatches():
            if hint.host not in targets:
                targets.insert(0, hint.host)
        # Keep probing previously seen machines even after Wi‑Fi/subnet changes.
        for host in sorted(self._known_hosts.keys(), key=lambda h: self._known_hosts[h], reverse=True):
            if host not in targets and host != self.lan_ip:
                targets.insert(0, host)
        if not targets:
            return

        sem = asyncio.Semaphore(TCP_SCAN_CONCURRENCY)

        async def _probe_if_open(host: str) -> None:
            async with sem:
                if not await self._port_open(host):
                    return
                await self.probe_host_tcp(host)

        await asyncio.gather(*(_probe_if_open(host) for host in targets))

    async def probe_host_tcp(self, host: str) -> Peer | None:
        host = (host or "").strip()
        if not host or host == self.lan_ip:
            return None
        body = self.presence_body()
        body["type"] = "presence_hello"
        envelope = {"body": body, "sig": sign_payload(self.cfg.team_secret, body)}
        line = (json.dumps(envelope, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, self.cfg.message_port),
                timeout=TCP_CONNECT_TIMEOUT_S,
            )
        except (OSError, asyncio.TimeoutError):
            return None
        try:
            writer.write(line)
            await writer.drain()
            raw = await asyncio.wait_for(reader.readline(), timeout=2.0)
        except (OSError, asyncio.TimeoutError):
            return None
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        if not raw:
            return None
        try:
            reply = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        if not isinstance(reply, dict):
            return None
        if not reply.get("ok"):
            err = str(reply.get("error") or "unknown")
            # "type" means team+sig matched on an older daemon without hello support.
            # UDP beacons should still discover it once codes match.
            if err in ("team", "sig"):
                self._note_mismatch(host, err)
                LOGGER.info(
                    "aidylink at %s rejected hello (%s) — group/code mismatch",
                    host,
                    err,
                )
            elif err == "type":
                self._note_mismatch(host, "old")
            return None
        reply_body = reply.get("body")
        reply_sig = reply.get("sig")
        if not isinstance(reply_body, dict):
            return None
        if not verify_payload(self.cfg.team_secret, reply_body, str(reply_sig or "")):
            LOGGER.debug("ignored tcp presence reply with bad signature from %s", host)
            self._note_mismatch(host, "sig")
            return None
        if not reply_body.get("host"):
            reply_body = dict(reply_body)
            reply_body["host"] = host
        else:
            announced = str(reply_body.get("host") or "")
            if announced.startswith("127.") or announced == "0.0.0.0":
                reply_body = dict(reply_body)
                reply_body["host"] = host
        return self.accept_presence(reply_body, host)
