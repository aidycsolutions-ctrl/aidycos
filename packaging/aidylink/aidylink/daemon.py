"""AidyLink user daemon: discovery + LAN + cloud poll + control socket."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from pathlib import Path
from typing import Any

from .cloud import AidyChatBridge
from .config import LinkConfig, load_config, save_config
from .discovery import DiscoveryService
from .lan import LanTransport
from .messages import LinkMessage
from .notify import notify
from .paths import control_socket_path, data_dir
from .router import MessageRouter

LOGGER = logging.getLogger(__name__)


class AidylinkDaemon:
    def __init__(self, cfg: LinkConfig) -> None:
        self.cfg = cfg
        self.discovery = DiscoveryService(cfg)
        self.lan = LanTransport(
            cfg,
            on_message=self._on_lan_message,
            on_presence=self.discovery.accept_presence,
            presence_body=self.discovery.presence_body,
        )
        self.cloud = AidyChatBridge(cfg)
        self.router = MessageRouter(cfg, self.discovery, self.lan, self.cloud)
        self._control_server: asyncio.AbstractServer | None = None
        self._inbox_path = data_dir() / "inbox.jsonl"

    def _on_lan_message(self, message: LinkMessage) -> None:
        self._persist(message)
        notify(message.from_name or "AidyLink", message.text)
        LOGGER.info("lan msg from %s: %s", message.from_name, message.text[:80])

    def _on_cloud_batch(self, batch: list[LinkMessage]) -> None:
        for message in batch:
            self._persist(message)
            notify(f"{message.from_name} (cloud)", message.text)

    def _persist(self, message: LinkMessage) -> None:
        try:
            with self._inbox_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(message.as_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            LOGGER.debug("inbox write failed: %s", exc)

    async def start(self) -> None:
        sock = control_socket_path()
        if sock.exists():
            try:
                sock.unlink()
            except OSError:
                pass

        await self.discovery.start()
        await self.lan.start()
        self._control_server = await asyncio.start_unix_server(
            self._handle_control,
            path=str(sock),
        )
        os.chmod(sock, 0o600)

        if self.cloud.enabled:
            try:
                uid = await asyncio.to_thread(self.cloud.refresh_self_id)
                if uid is not None:
                    save_config(self.cfg)
                    LOGGER.info("cloud self user_id=%s", uid)
            except Exception as exc:
                LOGGER.warning("cloud init: %s", exc)
            asyncio.create_task(
                self.cloud.poll_loop(self.cfg.cloud.poll_seconds, self._on_cloud_batch),
                name="aidylink-cloud-poll",
            )

        LOGGER.info(
            "AidyLink up as %s (%s) team=%s lan=%s",
            self.cfg.display_name,
            self.cfg.node_id[:8],
            self.cfg.team_id,
            self.discovery.lan_ip,
        )
        notify("AidyLink", f"En línea como {self.cfg.display_name}")

    async def stop(self) -> None:
        if self._control_server:
            self._control_server.close()
            await self._control_server.wait_closed()
            self._control_server = None
        await self.lan.stop()
        await self.discovery.stop()
        sock = control_socket_path()
        if sock.exists():
            try:
                sock.unlink()
            except OSError:
                pass

    async def _handle_control(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
            req = json.loads(raw.decode("utf-8")) if raw else {}
            resp = await self._dispatch(req if isinstance(req, dict) else {})
            writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()
        except Exception as exc:
            try:
                writer.write(
                    (json.dumps({"ok": False, "error": str(exc)}) + "\n").encode("utf-8")
                )
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch(self, req: dict[str, Any]) -> dict[str, Any]:
        cmd = str(req.get("cmd") or "")
        if cmd == "ping":
            return {"ok": True, "pong": True}
        if cmd == "status":
            return {
                "ok": True,
                "node_id": self.cfg.node_id,
                "display_name": self.cfg.display_name,
                "team_id": self.cfg.team_id,
                "lan_ip": self.discovery.lan_ip,
                "cloud_enabled": self.cloud.enabled,
                "peers": len(self.discovery.list_online()),
            }
        if cmd == "peers":
            peers = [
                {
                    "node_id": p.node_id,
                    "display_name": p.display_name,
                    "host": p.host,
                    "message_port": p.message_port,
                    "aidychat_user_id": p.aidychat_user_id,
                }
                for p in self.discovery.list_online()
            ]
            return {"ok": True, "peers": peers}
        if cmd == "send":
            target = str(req.get("to") or "")
            text = str(req.get("text") or "")
            host = str(req.get("host") or "").strip()
            port = req.get("port")
            if host:
                result = await self.router.send_direct(
                    host=host,
                    port=int(port or self.cfg.message_port),
                    text=text,
                    to_id=target or "*",
                )
            else:
                result = await self.router.send_text(target, text)
            if result.route != "failed" and result.message is not None:
                self._persist(result.message)
            return {
                "ok": result.route != "failed",
                "route": result.route,
                "detail": result.detail,
                "message": result.message.as_dict() if result.message else None,
            }
        if cmd == "inbox":
            limit = max(1, min(int(req.get("limit") or 100), 500))
            return {"ok": True, "messages": self._read_inbox(limit)}
        return {"ok": False, "error": f"unknown cmd: {cmd}"}

    def _read_inbox(self, limit: int) -> list[dict[str, Any]]:
        if not self._inbox_path.is_file():
            return []
        try:
            lines = self._inbox_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out


async def run_daemon(cfg: LinkConfig | None = None) -> None:
    config = cfg or load_config()
    if config is None:
        raise SystemExit(
            "Sin configuración. Ejecuta: aidylink init --name NOMBRE --team EQUIPO"
        )
    if not config.team_secret:
        raise SystemExit("Falta team_secret en la configuración")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    daemon = AidylinkDaemon(config)
    await daemon.start()

    stop_event = asyncio.Event()

    def _stop(*_args: object) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _stop())

    await stop_event.wait()
    await daemon.stop()


def control_request(payload: dict[str, Any], *, timeout: float = 5.0) -> dict[str, Any]:
    """Sync helper for CLI → daemon over the unix socket."""
    import socket

    path = str(control_socket_path())
    if not Path(path).exists():
        raise RuntimeError("Daemon no está corriendo (no hay socket de control)")
    raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(path)
        sock.sendall(raw)
        chunks: list[bytes] = []
        while True:
            piece = sock.recv(4096)
            if not piece:
                break
            chunks.append(piece)
            if b"\n" in piece:
                break
    line = b"".join(chunks).split(b"\n", 1)[0]
    return json.loads(line.decode("utf-8"))
