"""LAN mobile bridge: phone opens QR URL → WhatsApp-like chat via WebSocket.

The phone is a thin client of this PC. Messages are relayed through the host
daemon onto the existing LAN/cloud router; no team_secret leaves the PC.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import struct
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from . import MOBILE_PORT, PROTOCOL
from .config import LinkConfig
from .messages import LinkMessage
from .netutil import detect_lan_ip

LOGGER = logging.getLogger(__name__)

SendHandler = Callable[[str, str, str, str], Awaitable[dict[str, Any]]]
PeersProvider = Callable[[], list[dict[str, Any]]]
PinChecker = Callable[[str], bool]


MOBILE_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
<meta name="theme-color" content="#075e54"/>
<meta name="apple-mobile-web-app-capable" content="yes"/>
<title>AidyChat</title>
<style>
:root{--green:#075e54;--out:#d9fdd3;--bg:#e5ddd5;--ink:#111b21;--muted:#667781}
*{box-sizing:border-box}
html,body{margin:0;height:100%;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#111;color:var(--ink)}
#app{max-width:520px;margin:0 auto;height:100%;display:flex;flex-direction:column;background:var(--bg)}
header{background:var(--green);color:#fff;padding:12px 14px;display:flex;gap:10px;align-items:center}
header h1{font-size:16px;margin:0;font-weight:600}
header p{margin:2px 0 0;font-size:12px;opacity:.9}
#gate,#chat{flex:1;display:flex;flex-direction:column;min-height:0}
#gate{background:#fff;padding:24px 18px;gap:12px;justify-content:center}
#gate h2{margin:0 0 4px;font-size:20px}
#gate .hint{color:var(--muted);font-size:14px;line-height:1.4}
input,button,select{font:inherit}
input[type=text]{width:100%;padding:12px 14px;border:1px solid #d1d7db;border-radius:10px}
button.primary{background:var(--green);color:#fff;border:0;border-radius:24px;padding:12px 18px;font-weight:600}
button.primary:disabled{opacity:.5}
#status{color:#fecaca;font-size:13px;min-height:1.2em}
#peers{display:flex;gap:8px;overflow-x:auto;padding:8px 10px;background:#f0f2f5;border-bottom:1px solid #d1d7db}
.chip{flex:0 0 auto;background:#fff;border:1px solid #e9edef;border-radius:18px;padding:8px 12px;font-size:13px}
.chip.on{background:var(--out);border-color:#25d366}
#log{flex:1;overflow-y:auto;padding:12px 10px;display:flex;flex-direction:column;gap:6px}
.row{display:flex}
.row.me{justify-content:flex-end}
.bubble{max-width:82%;padding:6px 8px 4px;border-radius:8px;box-shadow:0 1px .5px rgba(0,0,0,.13);background:#fff}
.row.me .bubble{background:var(--out)}
.bubble .who{font-size:12px;font-weight:600;color:#027a67;margin-bottom:2px}
.bubble .txt{font-size:14.5px;white-space:pre-wrap;word-break:break-word}
.bubble .t{font-size:11px;color:var(--muted);text-align:right;margin-top:2px}
#composer{display:flex;gap:8px;padding:8px;background:#f0f2f5;align-items:center}
#composer input{flex:1;border-radius:22px;padding:12px 16px;border:0;background:#fff}
#composer button{border:0;background:var(--green);color:#fff;width:44px;height:44px;border-radius:22px;font-size:18px}
.sys{align-self:center;background:rgba(255,255,255,.85);color:var(--muted);font-size:12px;padding:4px 10px;border-radius:8px}
</style>
</head>
<body>
<div id="app">
  <header>
    <div>
      <h1>AidyChat</h1>
      <p id="sub">Misma Wi‑Fi que el PC</p>
    </div>
  </header>
  <section id="gate">
    <h2>Entrar al chat local</h2>
    <p class="hint">Escaneaste el QR del PC. Pon tu nombre y el código de 6 dígitos si no vino en el enlace.</p>
    <input id="name" type="text" placeholder="Tu nombre" autocomplete="name" maxlength="40"/>
    <input id="pin" type="text" inputmode="numeric" pattern="[0-9]*" placeholder="Código 123456" maxlength="6"/>
    <button class="primary" id="join">Entrar</button>
    <div id="status"></div>
  </section>
  <section id="chat" hidden>
    <div id="peers"></div>
    <div id="log"></div>
    <form id="composer">
      <input id="text" type="text" placeholder="Mensaje" autocomplete="off" enterkeyhint="send"/>
      <button type="submit" aria-label="Enviar">➤</button>
    </form>
  </section>
</div>
<script>
const qs=new URLSearchParams(location.search);
const hashPin=(location.hash||'').replace(/^#/,'').replace(/^p=/i,'');
const $=(id)=>document.getElementById(id);
const pinFromUrl=(qs.get('pin')||hashPin||'').replace(/\D/g,'').slice(0,6);
if(pinFromUrl) $('pin').value=pinFromUrl;
const savedName=localStorage.getItem('aidychat_mobile_name')||'';
if(savedName) $('name').value=savedName;

let ws=null, selfId='', selectedTo='*', peers=[];

function setStatus(t){$('status').textContent=t||'';}
function hhmm(ts){
  const d=new Date((ts||0)*1000);
  return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
}
function addBubble(msg){
  const me=msg.from_id===selfId;
  const row=document.createElement('div');
  row.className='row'+(me?' me':'');
  const b=document.createElement('div');
  b.className='bubble';
  if(!me && msg.from_name){
    const w=document.createElement('div'); w.className='who'; w.textContent=msg.from_name; b.appendChild(w);
  }
  const t=document.createElement('div'); t.className='txt'; t.textContent=msg.text||msg.filename||''; b.appendChild(t);
  const tm=document.createElement('div'); tm.className='t'; tm.textContent=hhmm(msg.ts); b.appendChild(tm);
  row.appendChild(b); $('log').appendChild(row); $('log').scrollTop=$('log').scrollHeight;
}
function addSys(text){
  const el=document.createElement('div'); el.className='sys'; el.textContent=text; $('log').appendChild(el);
}
function renderPeers(){
  const box=$('peers'); box.innerHTML='';
  const all=[{node_id:'*',display_name:'Este PC'}].concat(peers||[]);
  all.forEach(p=>{
    const c=document.createElement('button');
    c.type='button'; c.className='chip'+(selectedTo===p.node_id?' on':'');
    c.textContent=p.display_name||p.node_id;
    c.onclick=()=>{selectedTo=p.node_id; renderPeers();};
    box.appendChild(c);
  });
}
function connect(){
  const name=($('name').value||'').trim();
  const pin=($('pin').value||'').replace(/\D/g,'');
  if(name.length<2){setStatus('Escribe tu nombre'); return;}
  if(!/^\d{6}$/.test(pin)){setStatus('El código debe tener 6 dígitos'); return;}
  localStorage.setItem('aidychat_mobile_name', name);
  setStatus('Conectando…');
  $('join').disabled=true;
  const proto=location.protocol==='https:'?'wss':'ws';
  ws=new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen=()=>ws.send(JSON.stringify({type:'hello',pin,name,protocol:'aidylink/1'}));
  ws.onmessage=(ev)=>{
    let data; try{data=JSON.parse(ev.data);}catch(_){return;}
    if(data.type==='hello_ok'){
      selfId=data.self_id; peers=data.peers||[];
      $('sub').textContent=(data.host_name||'PC')+' · conectado';
      $('gate').hidden=true; $('chat').hidden=false;
      renderPeers();
      (data.history||[]).forEach(addBubble);
      addSys('Listo. Misma Wi‑Fi, mensajes por este PC.');
      setStatus('');
    } else if(data.type==='peers'){ peers=data.peers||[]; renderPeers(); }
    else if(data.type==='message'){ addBubble(data.message||data); }
    else if(data.type==='error'){ setStatus(data.error||'Error'); $('join').disabled=false; }
  };
  ws.onclose=()=>{
    setStatus('Desconectado. Vuelve a entrar con el código.');
    $('join').disabled=false;
    $('gate').hidden=false; $('chat').hidden=true;
  };
  ws.onerror=()=>setStatus('No se pudo conectar al PC. ¿Misma Wi‑Fi?');
}
$('join').onclick=connect;
$('composer').onsubmit=(e)=>{
  e.preventDefault();
  const text=($('text').value||'').trim();
  if(!text||!ws||ws.readyState!==1) return;
  ws.send(JSON.stringify({type:'send',to:selectedTo,text}));
  $('text').value='';
};
if(pinFromUrl && savedName){ /* wait for tap */ }
</script>
</body>
</html>
"""


@dataclass
class MobileSession:
    node_id: str
    display_name: str
    token: str
    writer: asyncio.StreamWriter
    connected_at: float = field(default_factory=time.time)


class MobileGateway:
    """HTTP + minimal WebSocket server for phones on the LAN."""

    def __init__(
        self,
        cfg: LinkConfig,
        *,
        check_pin: PinChecker,
        list_lan_peers: PeersProvider,
        send_from_mobile: SendHandler,
        port: int | None = None,
    ) -> None:
        self.cfg = cfg
        self.check_pin = check_pin
        self.list_lan_peers = list_lan_peers
        self.send_from_mobile = send_from_mobile
        self.port = int(port or MOBILE_PORT)
        self._server: asyncio.AbstractServer | None = None
        self._sessions: dict[str, MobileSession] = {}
        self._history: list[dict[str, Any]] = []

    @property
    def lan_ip(self) -> str:
        return detect_lan_ip()

    def pair_urls(self, pin: str) -> list[str]:
        pin = (pin or "").strip()
        ip = self.lan_ip
        base = f"http://{ip}:{self.port}/"
        if pin:
            return [f"{base}?pin={pin}", f"{base}#{pin}"]
        return [base]

    def list_sessions(self) -> list[dict[str, Any]]:
        return [
            {
                "node_id": s.node_id,
                "display_name": f"{s.display_name} (móvil)",
                "host": "mobile",
                "message_port": 0,
                "aidychat_user_id": None,
                "kind": "mobile",
            }
            for s in self._sessions.values()
        ]

    def remember(self, message: LinkMessage | dict[str, Any]) -> None:
        data = message.as_dict() if isinstance(message, LinkMessage) else dict(message)
        # Never push huge base64 blobs to phones.
        data.pop("media_b64", None)
        self._history.append(data)
        if len(self._history) > 200:
            self._history = self._history[-200:]

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle,
            host="0.0.0.0",
            port=self.port,
        )
        LOGGER.info("mobile gateway on http://%s:%s/", self.lan_ip, self.port)

    async def stop(self) -> None:
        for session in list(self._sessions.values()):
            try:
                session.writer.close()
            except Exception:
                pass
        self._sessions.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def broadcast_message(self, message: LinkMessage | dict[str, Any]) -> None:
        data = message.as_dict() if isinstance(message, LinkMessage) else dict(message)
        data.pop("media_b64", None)
        self.remember(data)
        dead: list[str] = []
        payload = json.dumps({"type": "message", "message": data}, ensure_ascii=False)
        for node_id, session in self._sessions.items():
            try:
                await self._ws_send_text(session.writer, payload)
            except Exception:
                dead.append(node_id)
        for node_id in dead:
            self._sessions.pop(node_id, None)

    async def deliver_to(self, node_id: str, message: LinkMessage) -> bool:
        session = self._sessions.get(node_id)
        if session is None:
            return False
        data = message.as_dict()
        data.pop("media_b64", None)
        self.remember(data)
        try:
            await self._ws_send_text(
                session.writer,
                json.dumps({"type": "message", "message": data}, ensure_ascii=False),
            )
            return True
        except Exception:
            self._sessions.pop(node_id, None)
            return False

    async def push_peers(self) -> None:
        peers = self.list_lan_peers()
        payload = json.dumps({"type": "peers", "peers": peers}, ensure_ascii=False)
        dead: list[str] = []
        for node_id, session in self._sessions.items():
            try:
                await self._ws_send_text(session.writer, payload)
            except Exception:
                dead.append(node_id)
        for node_id in dead:
            self._sessions.pop(node_id, None)

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=8.0)
            if not request_line:
                writer.close()
                return
            line = request_line.decode("iso-8859-1", errors="replace").strip()
            parts = line.split()
            if len(parts) < 2:
                await self._http_response(writer, 400, b"bad request")
                return
            method, target = parts[0].upper(), parts[1]
            headers = await self._read_headers(reader)
            parsed = urlparse(target)
            path = parsed.path or "/"

            if method == "GET" and path in ("/", "/index.html"):
                body = MOBILE_HTML.encode("utf-8")
                await self._http_response(
                    writer,
                    200,
                    body,
                    content_type="text/html; charset=utf-8",
                )
                return
            if method == "GET" and path == "/health":
                body = json.dumps(
                    {
                        "ok": True,
                        "protocol": PROTOCOL,
                        "host": self.cfg.display_name,
                        "port": self.port,
                    }
                ).encode("utf-8")
                await self._http_response(writer, 200, body, content_type="application/json")
                return
            if method == "GET" and path == "/ws":
                await self._websocket(reader, writer, headers)
                return
            await self._http_response(writer, 404, b"not found")
        except Exception as exc:
            LOGGER.debug("mobile client error: %s", exc)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _read_headers(self, reader: asyncio.StreamReader) -> dict[str, str]:
        headers: dict[str, str] = {}
        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout=8.0)
            if not raw or raw in (b"\r\n", b"\n"):
                break
            try:
                text = raw.decode("iso-8859-1")
            except UnicodeDecodeError:
                continue
            if ":" not in text:
                continue
            key, value = text.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        return headers

    async def _http_response(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        body: bytes,
        *,
        content_type: str = "text/plain; charset=utf-8",
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 101: "Switching Protocols"}.get(
            status, "OK"
        )
        lines = [
            f"HTTP/1.1 {status} {reason}",
            f"Content-Type: {content_type}",
            f"Content-Length: {len(body)}",
            "Connection: close",
            "Cache-Control: no-store",
            "Access-Control-Allow-Origin: *",
        ]
        for key, value in extra_headers or []:
            lines.append(f"{key}: {value}")
        header = ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1")
        writer.write(header + body)
        await writer.drain()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    async def _websocket(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
    ) -> None:
        key = headers.get("sec-websocket-key", "").strip()
        if not key or headers.get("upgrade", "").lower() != "websocket":
            await self._http_response(writer, 400, b"expected websocket")
            return
        accept = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()
        ).decode("ascii")
        reply = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        ).encode("iso-8859-1")
        writer.write(reply)
        await writer.drain()

        session: MobileSession | None = None
        try:
            while True:
                data = await self._ws_recv_text(reader)
                if data is None:
                    break
                try:
                    msg = json.loads(data)
                except ValueError:
                    await self._ws_send_text(
                        writer, json.dumps({"type": "error", "error": "JSON inválido"})
                    )
                    continue
                if not isinstance(msg, dict):
                    continue
                mtype = str(msg.get("type") or "")
                if session is None:
                    if mtype != "hello":
                        await self._ws_send_text(
                            writer,
                            json.dumps(
                                {"type": "error", "error": "Primero envía hello con pin y nombre"}
                            ),
                        )
                        continue
                    pin = str(msg.get("pin") or "").strip()
                    name = str(msg.get("name") or "").strip()[:40]
                    if len(name) < 2:
                        await self._ws_send_text(
                            writer, json.dumps({"type": "error", "error": "Nombre demasiado corto"})
                        )
                        continue
                    if not self.check_pin(pin):
                        await self._ws_send_text(
                            writer,
                            json.dumps(
                                {
                                    "type": "error",
                                    "error": "Código incorrecto o expirado. En el PC: Emparejar → Mostrar código.",
                                }
                            ),
                        )
                        continue
                    node_id = f"mobile:{uuid.uuid4().hex[:12]}"
                    session = MobileSession(
                        node_id=node_id,
                        display_name=name,
                        token=secrets.token_urlsafe(16),
                        writer=writer,
                    )
                    self._sessions[node_id] = session
                    peers = self.list_lan_peers()
                    await self._ws_send_text(
                        writer,
                        json.dumps(
                            {
                                "type": "hello_ok",
                                "self_id": node_id,
                                "host_name": self.cfg.display_name,
                                "team_id": self.cfg.team_id,
                                "peers": peers,
                                "history": self._history[-80:],
                            },
                            ensure_ascii=False,
                        ),
                    )
                    LOGGER.info("mobile joined: %s (%s)", name, node_id)
                    continue

                if mtype == "send":
                    text = str(msg.get("text") or "").strip()
                    to_id = str(msg.get("to") or "*").strip() or "*"
                    if not text:
                        continue
                    result = await self.send_from_mobile(
                        session.node_id, session.display_name, to_id, text
                    )
                    if not result.get("ok"):
                        await self._ws_send_text(
                            writer,
                            json.dumps(
                                {
                                    "type": "error",
                                    "error": result.get("error") or "No se pudo enviar",
                                }
                            ),
                        )
        except Exception as exc:
            LOGGER.debug("ws session ended: %s", exc)
        finally:
            if session is not None:
                self._sessions.pop(session.node_id, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _ws_send_text(self, writer: asyncio.StreamWriter, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])  # fin + text
        n = len(payload)
        if n < 126:
            header.append(n)
        elif n < (1 << 16):
            header.append(126)
            header.extend(struct.pack("!H", n))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", n))
        writer.write(bytes(header) + payload)
        await writer.drain()

    async def _ws_recv_text(self, reader: asyncio.StreamReader) -> str | None:
        header = await reader.readexactly(2)
        opcode = header[0] & 0x0F
        masked = (header[1] & 0x80) != 0
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", await reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", await reader.readexactly(8))[0]
        mask = await reader.readexactly(4) if masked else b""
        raw = await reader.readexactly(length)
        if masked:
            raw = bytes(b ^ mask[i % 4] for i, b in enumerate(raw))
        if opcode == 0x8:  # close
            return None
        if opcode == 0x9:  # ping → pong
            # ignore control for MVP
            return ""
        if opcode != 0x1:
            return ""
        return raw.decode("utf-8", errors="replace")
