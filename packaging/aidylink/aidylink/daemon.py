"""AidyLink user daemon: discovery + LAN + cloud poll + control socket."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import signal
from pathlib import Path
from typing import Any

from .cloud import AidyChatBridge
from .config import LinkConfig, load_config, save_config
from .discovery import DiscoveryService
from .lan import LanTransport
from .messages import LinkMessage
from .mobile_gateway import MobileGateway
from .notify import notify
from .pairing import PairingService
from .paths import control_socket_path, data_dir, runtime_dir, runtime_dir
from .router import MessageRouter

LOGGER = logging.getLogger(__name__)


class AidylinkDaemon:
    def __init__(self, cfg: LinkConfig) -> None:
        self.cfg = cfg
        self.discovery = DiscoveryService(cfg)
        self.pairing = PairingService(cfg)
        self.lan = LanTransport(
            cfg,
            on_message=self._on_lan_message,
            on_presence=self.discovery.accept_presence,
            presence_body=self.discovery.presence_body,
            on_pair_request=self.pairing.handle_request,
        )
        self.cloud = AidyChatBridge(cfg)
        self.router = MessageRouter(cfg, self.discovery, self.lan, self.cloud)
        self.mobile = MobileGateway(
            cfg,
            check_pin=self.pairing.verify_pin,
            list_lan_peers=self._mobile_peer_list,
            send_from_mobile=self._send_from_mobile,
        )
        self._control_server: asyncio.AbstractServer | None = None
        self._inbox_path = data_dir() / "inbox.jsonl"
        self._media_dir = data_dir() / "media"
        self._media_dir.mkdir(parents=True, exist_ok=True)
        self._mobile_fanout_task: asyncio.Task | None = None

    def _on_lan_message(self, message: LinkMessage) -> None:
        self._materialize_media(message)
        self._persist(message)
        preview = message.display_text() or message.filename or "Mensaje"
        notify(message.from_name or "AidyChat", preview)
        LOGGER.info("lan msg from %s: %s", message.from_name, preview[:80])
        self._schedule_mobile_fanout(message)

    def _on_cloud_batch(self, batch: list[LinkMessage]) -> None:
        for message in batch:
            self._persist(message)
            notify(f"{message.from_name} (cloud)", message.display_text() or "Mensaje")
            self._schedule_mobile_fanout(message)

    def _mobile_peer_list(self) -> list[dict[str, Any]]:
        return [
            {
                "node_id": p.node_id,
                "display_name": p.display_name,
                "host": p.host,
            }
            for p in self.discovery.list_online()
        ]

    def _schedule_mobile_fanout(self, message: LinkMessage) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.mobile.broadcast_message(message))

    async def _send_from_mobile(
        self,
        from_id: str,
        from_name: str,
        to_id: str,
        text: str,
        *,
        media_b64: str = "",
        filename: str = "",
        mime: str = "",
    ) -> dict[str, Any]:
        from .messages import MAX_ATTACHMENT_BYTES

        text = (text or "").strip()
        media_b64 = (media_b64 or "").strip()
        filename = (filename or "").strip()
        mime = (mime or "").strip()
        if not text and not media_b64:
            return {"ok": False, "error": "mensaje vacío"}

        kind = "text"
        if media_b64:
            try:
                raw = base64.b64decode(media_b64, validate=False)
            except Exception:
                return {"ok": False, "error": "archivo inválido"}
            if not raw:
                return {"ok": False, "error": "archivo vacío"}
            if len(raw) > MAX_ATTACHMENT_BYTES:
                return {"ok": False, "error": "Máximo 15 MB por archivo"}
            if not mime:
                mime = "application/octet-stream"
            if mime.startswith("image/"):
                kind = "image"
            elif mime.startswith("video/"):
                kind = "video"
            else:
                kind = "file"
            if not filename:
                if kind == "image":
                    filename = "foto.jpg"
                elif kind == "video":
                    filename = "video.mp4"
                else:
                    filename = "archivo.bin"

        target = (to_id or "*").strip() or "*"
        message = LinkMessage.create(
            from_id=from_id,
            from_name=f"{from_name} (móvil)",
            to_id=self.cfg.node_id if target == "*" else target,
            text=text,
            team_id=self.cfg.team_id,
            via="lan",
            kind=kind,
            filename=filename,
            mime=mime,
            media_b64=media_b64,
        )

        route = "host"
        detail = ""
        mobile_ids = {m["node_id"] for m in self.mobile.list_sessions()}
        if target in mobile_ids:
            route = "mobile"
        elif target not in ("*", self.cfg.node_id):
            # Keep media_b64 for LAN transit, then save a local copy.
            result = await self.router.send_message(target, message)
            if result.route == "failed":
                return {
                    "ok": False,
                    "route": "failed",
                    "error": result.detail or "No se pudo enviar",
                    "detail": result.detail,
                }
            route = result.route
            detail = result.detail
            if result.message is not None:
                message = result.message

        self._materialize_media(message)
        self._persist(message)
        await self.mobile.broadcast_message(message)
        notify(message.from_name, message.display_text() or filename or "Archivo")
        return {
            "ok": True,
            "route": route,
            "detail": detail,
            "message": message.as_dict(),
        }

    def _safe_name(self, name: str) -> str:
        cleaned = re.sub(r"[^\w.\-()+ ]+", "_", (name or "archivo").strip()) or "archivo"
        return cleaned[:120]

    def _materialize_media(self, message: LinkMessage) -> None:
        """Decode transit media_b64 into a local file and drop the payload."""
        if not message.media_b64:
            if message.media_path and Path(message.media_path).is_file():
                return
            return
        try:
            raw = base64.b64decode(message.media_b64, validate=False)
        except Exception as exc:
            LOGGER.warning("bad media payload: %s", exc)
            message.media_b64 = ""
            return
        filename = self._safe_name(message.filename or f"{message.msg_id}.bin")
        target = self._media_dir / f"{message.msg_id[:8]}_{filename}"
        try:
            target.write_bytes(raw)
            message.media_path = str(target)
            message.media_b64 = ""
            if not message.kind or message.kind == "text":
                message.kind = "image" if (message.mime or "").startswith("image/") else "file"
        except OSError as exc:
            LOGGER.warning("media save failed: %s", exc)

    def _persist(self, message: LinkMessage) -> None:
        self._materialize_media(message)
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

        # Bind the UI control socket first so a partial start never leaves
        # LAN ports up without a way for the window to talk to the daemon.
        self._control_server = await asyncio.start_unix_server(
            self._handle_control,
            path=str(sock),
        )
        os.chmod(sock, 0o600)
        try:
            (runtime_dir() / "aidylink.pid").write_text(
                f"{os.getpid()}\n", encoding="utf-8"
            )
        except OSError:
            pass

        await self.discovery.start()
        await self.lan.start()
        try:
            await self.mobile.start()
        except OSError as exc:
            LOGGER.warning("mobile gateway no arrancó (%s); el chat de PC sigue OK", exc)

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
        await self.mobile.stop()
        await self.lan.stop()
        await self.discovery.stop()
        sock = control_socket_path()
        if sock.exists():
            try:
                sock.unlink()
            except OSError:
                pass
        pid_path = runtime_dir() / "aidylink.pid"
        if pid_path.exists():
            try:
                pid_path.unlink()
            except OSError:
                pass
        pid_path = runtime_dir() / "aidylink.pid"
        if pid_path.exists():
            try:
                pid_path.unlink()
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
            mismatches = self.discovery.list_mismatches()
            return {
                "ok": True,
                "node_id": self.cfg.node_id,
                "display_name": self.cfg.display_name,
                "team_id": self.cfg.team_id,
                "lan_ip": self.discovery.lan_ip,
                "cloud_enabled": self.cloud.enabled,
                "peers": len(self.discovery.list_online()),
                "mismatches": len(mismatches),
            }
        if cmd == "peers":
            peers = [
                {
                    "node_id": p.node_id,
                    "display_name": p.display_name,
                    "host": p.host,
                    "message_port": p.message_port,
                    "aidychat_user_id": p.aidychat_user_id,
                    "kind": "lan",
                }
                for p in self.discovery.list_online()
            ]
            peers.extend(self.mobile.list_sessions())
            mismatches = [
                {
                    "host": h.host,
                    "reason": h.reason,
                    "display_name": h.display_name,
                }
                for h in self.discovery.list_mismatches()
            ]
            return {"ok": True, "peers": peers, "mismatches": mismatches}
        if cmd == "pair_host":
            info = self.pairing.start_host()
            pin = str(info.get("pin") or "")
            urls = self.mobile.pair_urls(pin)
            info["mobile_urls"] = urls
            info["mobile_url"] = urls[0] if urls else ""
            info["mobile_port"] = self.mobile.port
            info["lan_ip"] = self.mobile.lan_ip
            return info
        if cmd == "pair_stop":
            self.pairing.stop()
            return {"ok": True}
        if cmd == "pair_status":
            status = self.pairing.status()
            if status.get("active") and status.get("pin"):
                urls = self.mobile.pair_urls(str(status["pin"]))
                status["mobile_urls"] = urls
                status["mobile_url"] = urls[0] if urls else ""
            status["mobiles"] = len(self.mobile.list_sessions())
            return status
        if cmd == "pair_join":
            pin = str(req.get("pin") or "").strip()
            hosts = [h.host for h in self.discovery.list_mismatches()]
            hosts.extend(p.host for p in self.discovery.list_online())
            result = await self.pairing.join(pin, hosts=hosts)
            if result.get("ok"):
                self.cfg.team_id = str(result["team_id"])
                self.cfg.team_secret = str(result["team_secret"])
                save_config(self.cfg)
                self.discovery.peers.clear()
                self.discovery.mismatches.clear()
                notify(
                    "AidyChat",
                    f"Emparejado con {result.get('host_name') or 'otro PC'}",
                )
            return result
        if cmd == "send":
            target = str(req.get("to") or "")
            text = str(req.get("text") or "")
            host = str(req.get("host") or "").strip()
            port = req.get("port")
            file_path = str(req.get("file") or "").strip()

            # PC → phone connected to this host.
            if target.startswith("mobile:") and not file_path and not host:
                message = LinkMessage.create(
                    from_id=self.cfg.node_id,
                    from_name=self.cfg.display_name,
                    to_id=target,
                    text=text,
                    team_id=self.cfg.team_id,
                    via="lan",
                )
                ok = await self.mobile.deliver_to(target, message)
                if ok:
                    self._persist(message)
                return {
                    "ok": ok,
                    "route": "mobile" if ok else "failed",
                    "detail": target if ok else "móvil desconectado",
                    "message": message.as_dict() if ok else None,
                }

            if file_path:
                result = await self.router.send_file(target, Path(file_path), caption=text)
            elif host:
                result = await self.router.send_direct(
                    host=host,
                    port=int(port or self.cfg.message_port),
                    text=text,
                    to_id=target or "*",
                )
            else:
                result = await self.router.send_text(target, text)
            if result.route != "failed" and result.message is not None:
                # Keep a local copy of outgoing attachments for the chat UI.
                if result.message.media_b64 and not result.message.media_path:
                    self._materialize_media(result.message)
                elif result.message.media_path and result.message.media_b64:
                    # Persist without re-encoding the original path payload.
                    result.message.media_b64 = ""
                self._persist(result.message)
                self._schedule_mobile_fanout(result.message)
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
    try:
        await daemon.start()
    except Exception:
        try:
            await daemon.stop()
        except Exception:
            pass
        raise

    stop_event = asyncio.Event()

    def _stop(*_args: object) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _stop())

    try:
        await stop_event.wait()
    finally:
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
