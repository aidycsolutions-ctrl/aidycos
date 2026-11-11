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

from pathlib import Path

from . import MOBILE_PORT, PROTOCOL
from .config import LinkConfig
from .messages import MAX_ATTACHMENT_BYTES, LinkMessage
from .netutil import detect_lan_ip

LOGGER = logging.getLogger(__name__)

SendHandler = Callable[..., Awaitable[dict[str, Any]]]
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
#status{color:#b91c1c;font-size:13px;min-height:1.2em}
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
.bubble img.media{display:block;max-width:100%;max-height:260px;border-radius:6px;margin:2px 0 4px}
.bubble a.file{display:inline-block;margin:2px 0 4px;color:#027a67;font-size:14px;word-break:break-all}
#composer{display:flex;gap:8px;padding:8px;background:#f0f2f5;align-items:center}
#composer input[type=text]{flex:1;border-radius:22px;padding:12px 16px;border:0;background:#fff}
#composer button.send{border:0;background:var(--green);color:#fff;width:44px;height:44px;border-radius:22px;font-size:18px}
#composer button.attach{border:0;background:#fff;color:#54656f;width:44px;height:44px;border-radius:22px;font-size:20px}
#uploadHint{display:none;padding:6px 12px;background:#fff3cd;color:#664d03;font-size:12px}
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
    <div id="uploadHint">Enviando archivo…</div>
    <div id="log"></div>
    <form id="composer">
      <button type="button" class="attach" id="attach" aria-label="Adjuntar">📎</button>
      <input id="file" type="file" accept="image/*,*/*" hidden/>
      <input id="text" type="text" placeholder="Mensaje" autocomplete="off" enterkeyhint="send"/>
      <button type="submit" class="send" aria-label="Enviar">➤</button>
    </form>
  </section>
</div>
<script>
const MAX_BYTES=15*1024*1024;
const TOKEN_KEY='aidychat_mobile_token';
const NAME_KEY='aidychat_mobile_name';
const qs=new URLSearchParams(location.search);
const hashPin=(location.hash||'').replace(/^#/,'').replace(/^p=/i,'');
const $=(id)=>document.getElementById(id);
const pinFromUrl=(qs.get('pin')||hashPin||'').replace(/\D/g,'').slice(0,6);
if(pinFromUrl) $('pin').value=pinFromUrl;
const savedName=localStorage.getItem(NAME_KEY)||'';
if(savedName) $('name').value=savedName;

let ws=null, selfId='', selectedTo='*', peers=[], busy=false;
let token=localStorage.getItem(TOKEN_KEY)||'';
let pickingFile=false, reconnecting=false, everJoined=false, wantLive=false;
const seenIds=new Set();
let pendingHello=null;

function setStatus(t){$('status').textContent=t||'';}
function setUpload(t){
  const el=$('uploadHint');
  if(!t){el.style.display='none'; el.textContent=''; return;}
  el.style.display='block'; el.textContent=t;
}
function hhmm(ts){
  const d=new Date((ts||0)*1000);
  return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
}
function mediaSrc(msg){
  if(msg.media_url) return msg.media_url;
  if(msg.msg_id) return '/media/'+encodeURIComponent(msg.msg_id);
  return '';
}
function addBubble(msg){
  const mid=String(msg.msg_id||'');
  if(mid){
    if(seenIds.has(mid)) return;
    seenIds.add(mid);
  }
  const me=msg.from_id===selfId;
  const row=document.createElement('div');
  row.className='row'+(me?' me':'');
  const b=document.createElement('div');
  b.className='bubble';
  if(!me && msg.from_name){
    const w=document.createElement('div'); w.className='who'; w.textContent=msg.from_name; b.appendChild(w);
  }
  const kind=msg.kind||'text';
  const src=mediaSrc(msg);
  const isImage=kind==='image' || (msg.mime||'').startsWith('image/');
  const isVideo=kind==='video' || (msg.mime||'').startsWith('video/');
  if(isImage && src){
    const img=document.createElement('img');
    img.className='media'; img.loading='lazy'; img.alt=msg.filename||'Imagen';
    img.src=src;
    img.onclick=()=>window.open(src,'_blank');
    b.appendChild(img);
  } else if(isVideo && src){
    const v=document.createElement('video');
    v.className='media'; v.controls=true; v.preload='metadata'; v.src=src;
    b.appendChild(v);
  } else if((kind==='file' || kind==='image' || kind==='video') && src){
    const a=document.createElement('a');
    a.className='file'; a.href=src; a.target='_blank'; a.rel='noopener';
    a.textContent='📎 '+(msg.filename||'Archivo');
    b.appendChild(a);
  }
  const body=msg.text||'';
  if(body){
    const t=document.createElement('div'); t.className='txt'; t.textContent=body; b.appendChild(t);
  } else if(!src && (kind==='file'||kind==='video')){
    const t=document.createElement('div'); t.className='txt'; t.textContent=msg.filename||'Archivo'; b.appendChild(t);
  }
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
function showChat(hostName){
  $('sub').textContent=(hostName||'PC')+(ws&&ws.readyState===1?' · conectado':' · reconectando…');
  $('gate').hidden=true;
  $('chat').hidden=false;
  everJoined=true;
}
function openSocket(hello){
  return new Promise((resolve,reject)=>{
    pendingHello=hello;
    const proto=location.protocol==='https:'?'wss':'ws';
    const sock=new WebSocket(`${proto}://${location.host}/ws`);
    let settled=false;
    const done=(fn,arg)=>{ if(settled) return; settled=true; fn(arg); };
    sock.onopen=()=>{
      ws=sock;
      sock.send(JSON.stringify(Object.assign({type:'hello',protocol:'aidylink/1'}, hello)));
    };
    sock.onmessage=(ev)=>{
      let data; try{data=JSON.parse(ev.data);}catch(_){return;}
      if(data.type==='hello_ok'){
        selfId=data.self_id;
        if(data.token){ token=data.token; localStorage.setItem(TOKEN_KEY, token); }
        peers=data.peers||[];
        showChat(data.host_name);
        renderPeers();
        (data.history||[]).forEach(addBubble);
        if(!data.resume) addSys('Listo. Fotos/vídeos: clip 📎 (máx. 15 MB).');
        setStatus('');
        $('join').disabled=false;
        done(resolve, data);
      } else if(data.type==='peers'){ peers=data.peers||[]; renderPeers(); }
      else if(data.type==='message'){ addBubble(data.message||data); }
      else if(data.type==='error'){
        setUpload(''); busy=false;
        if(!everJoined){ setStatus(data.error||'Error'); $('join').disabled=false; }
        else alert(data.error||'Error');
        done(reject, new Error(data.error||'Error'));
      }
    };
    sock.onclose=()=>{
      ws=null;
      if(!settled){ done(reject, new Error('Conexión cerrada')); return; }
      if(pickingFile){ $('sub').textContent='PC · eligiendo archivo…'; return; }
      if(wantLive && token){
        $('sub').textContent='PC · reconectando…';
        scheduleReconnect();
        return;
      }
      if(everJoined){
        setStatus('Desconectado. Pulsa Entrar o recarga.');
        $('join').disabled=false;
      }
    };
    sock.onerror=()=>{ if(!everJoined) setStatus('No se pudo conectar al PC. ¿Misma Wi‑Fi?'); };
  });
}
function scheduleReconnect(){
  if(reconnecting||!wantLive||!token) return;
  reconnecting=true;
  setTimeout(async()=>{
    reconnecting=false;
    if(!wantLive||(ws&&ws.readyState===1)) return;
    try{
      await openSocket({token, name:($('name').value||savedName||'Móvil').trim()});
    }catch(_){
      setTimeout(scheduleReconnect, 1500);
    }
  }, 400);
}
async function ensureLive(){
  if(ws&&ws.readyState===1&&token) return;
  const name=($('name').value||savedName||'').trim();
  if(token){
    await openSocket({token, name:name||'Móvil'});
    return;
  }
  throw new Error('Sin sesión. Entra otra vez con el código.');
}
async function connect(){
  const name=($('name').value||'').trim();
  const pin=($('pin').value||'').replace(/\D/g,'');
  if(name.length<2){setStatus('Escribe tu nombre'); return;}
  localStorage.setItem(NAME_KEY, name);
  setStatus('Conectando…');
  $('join').disabled=true;
  wantLive=true;
  try{
    if(token){
      try{ await openSocket({token, name}); return; }
      catch(_){ /* token viejo: probar pin */ }
    }
    if(!/^\d{6}$/.test(pin)){ setStatus('El código debe tener 6 dígitos'); $('join').disabled=false; return; }
    await openSocket({pin, name});
  }catch(err){
    setStatus(err.message||'No se pudo conectar');
    $('join').disabled=false;
  }
}
function compressImage(file){
  return new Promise((resolve,reject)=>{
    const url=URL.createObjectURL(file);
    const img=new Image();
    img.onload=()=>{
      const max=1600;
      let w=img.width, h=img.height;
      if(w>max || h>max){
        const scale=Math.min(max/w, max/h);
        w=Math.round(w*scale); h=Math.round(h*scale);
      }
      const canvas=document.createElement('canvas');
      canvas.width=w; canvas.height=h;
      canvas.getContext('2d').drawImage(img,0,0,w,h);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob)=>{
        if(!blob){ reject(new Error('No se pudo comprimir la foto')); return; }
        resolve({
          blob,
          filename:(file.name||'foto').replace(/\.[^.]+$/,'')+'.jpg',
          mime:'image/jpeg'
        });
      }, 'image/jpeg', 0.82);
    };
    img.onerror=()=>{URL.revokeObjectURL(url); reject(new Error('No se pudo leer la imagen'));};
    img.src=url;
  });
}
async function prepareFile(file){
  if(file.size>MAX_BYTES) throw new Error('Máximo 15 MB (el vídeo/foto es más grande)');
  if((file.type||'').startsWith('image/') && file.size>250000){
    return compressImage(file);
  }
  return {blob:file, filename:file.name||'archivo', mime:file.type||'application/octet-stream'};
}
async function sendFile(file){
  if(busy) return;
  busy=true;
  pickingFile=false;
  setUpload('Preparando '+(file.name||'archivo')+'…');
  try{
    // La cámara suele matar el WebSocket: subimos por HTTP y luego reconectamos.
    if(!(ws&&ws.readyState===1)||!token){
      setUpload('Reconectando…');
      try{ await ensureLive(); }catch(_){ /* upload usa token guardado */ }
    }
    if(!token) throw new Error('Sin sesión. Entra otra vez con el código del QR.');
    const payload=await prepareFile(file);
    if(payload.blob.size>MAX_BYTES) throw new Error('Máximo 15 MB por archivo');
    setUpload('Enviando '+(payload.filename||'archivo')+'…');
    const caption=($('text').value||'').trim();
    const resp=await fetch('/api/upload', {
      method:'POST',
      headers:{
        'Authorization':'Bearer '+token,
        'X-Aidy-To': selectedTo,
        'X-Aidy-Filename': payload.filename||'archivo',
        'X-Aidy-Mime': payload.mime||'application/octet-stream',
        'X-Aidy-Text': caption,
        'Content-Type': 'application/octet-stream'
      },
      body: payload.blob
    });
    const data=await resp.json().catch(()=>({}));
    if(!resp.ok || data.ok===false){
      throw new Error(data.error||('Error al subir ('+resp.status+')'));
    }
    if(data.message) addBubble(data.message);
    $('text').value='';
    setUpload('');
    if(!(ws&&ws.readyState===1)) scheduleReconnect();
  }catch(err){
    setUpload('');
    alert(err.message||String(err));
    scheduleReconnect();
  }finally{
    busy=false;
    pickingFile=false;
  }
}
$('join').onclick=connect;
$('attach').onclick=()=>{
  pickingFile=true;
  $('file').click();
  // Si el usuario cancela el picker, soltar el flag.
  setTimeout(()=>{ if(pickingFile && !busy) pickingFile=false; }, 120000);
};
$('file').onchange=()=>{
  const f=$('file').files && $('file').files[0];
  $('file').value='';
  if(f) sendFile(f);
  else pickingFile=false;
};
$('composer').onsubmit=async (e)=>{
  e.preventDefault();
  const text=($('text').value||'').trim();
  if(!text||busy) return;
  try{
    await ensureLive();
    ws.send(JSON.stringify({type:'send',to:selectedTo,text}));
    $('text').value='';
  }catch(err){
    alert(err.message||String(err));
  }
};
document.addEventListener('visibilitychange', ()=>{
  if(document.visibilityState==='visible' && wantLive && token && !(ws&&ws.readyState===1)){
    scheduleReconnect();
  }
});
window.addEventListener('pageshow', ()=>{
  if(wantLive && token && !(ws&&ws.readyState===1)) scheduleReconnect();
});
if(token && savedName){
  // Reanudar sesión previa sin pedir PIN otra vez.
  wantLive=true;
  connect();
}
</script>
</body>
</html>
"""


TOKEN_TTL_S = 12 * 3600.0


@dataclass
class MobileIdentity:
    node_id: str
    display_name: str
    token: str
    expires_at: float = field(default_factory=lambda: time.time() + TOKEN_TTL_S)

    @property
    def active(self) -> bool:
        return time.time() <= self.expires_at

    def touch(self) -> None:
        self.expires_at = time.time() + TOKEN_TTL_S


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
        self._idents: dict[str, MobileIdentity] = {}  # token -> identity
        self._history: list[dict[str, Any]] = []
        self._media_index: dict[str, Path] = {}

    def _purge_idents(self) -> None:
        dead = [tok for tok, ident in self._idents.items() if not ident.active]
        for tok in dead:
            self._idents.pop(tok, None)

    def resolve_token(self, token: str) -> MobileIdentity | None:
        self._purge_idents()
        ident = self._idents.get((token or "").strip())
        if ident is None or not ident.active:
            return None
        ident.touch()
        return ident

    def _register_identity(
        self,
        *,
        name: str,
        token: str | None = None,
        node_id: str | None = None,
    ) -> MobileIdentity:
        self._purge_idents()
        if token:
            existing = self._idents.get(token)
            if existing and existing.active:
                existing.display_name = name or existing.display_name
                existing.touch()
                return existing
        ident = MobileIdentity(
            node_id=node_id or f"mobile:{uuid.uuid4().hex[:12]}",
            display_name=name,
            token=token or secrets.token_urlsafe(18),
        )
        self._idents[ident.token] = ident
        return ident

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

    def _public_message(self, message: LinkMessage | dict[str, Any]) -> dict[str, Any]:
        data = message.as_dict() if isinstance(message, LinkMessage) else dict(message)
        data.pop("media_b64", None)
        msg_id = str(data.get("msg_id") or "")
        media_path = str(data.get("media_path") or "")
        if msg_id and media_path and Path(media_path).is_file():
            self._media_index[msg_id] = Path(media_path)
            data["media_url"] = f"/media/{msg_id}"
            data["has_media"] = True
        elif msg_id and msg_id in self._media_index:
            data["media_url"] = f"/media/{msg_id}"
            data["has_media"] = True
        # Paths are host-local; phones should use media_url.
        data.pop("media_path", None)
        return data

    def remember(self, message: LinkMessage | dict[str, Any]) -> None:
        data = self._public_message(message)
        self._history.append(data)
        if len(self._history) > 200:
            self._history = self._history[-200:]
        if len(self._media_index) > 400:
            keep = {str(item.get("msg_id") or "") for item in self._history}
            self._media_index = {k: v for k, v in self._media_index.items() if k in keep}

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
        self._idents.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def broadcast_message(self, message: LinkMessage | dict[str, Any]) -> None:
        data = self._public_message(message)
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
        data = self._public_message(message)
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
            if method == "GET" and path.startswith("/media/"):
                await self._serve_media(writer, path[len("/media/") :])
                return
            if method == "POST" and path == "/api/upload":
                await self._http_upload(reader, writer, headers)
                return
            if method == "OPTIONS" and path == "/api/upload":
                await self._http_response(
                    writer,
                    200,
                    b"",
                    extra_headers=[
                        ("Access-Control-Allow-Methods", "POST, OPTIONS"),
                        (
                            "Access-Control-Allow-Headers",
                            "Authorization, Content-Type, X-Aidy-To, X-Aidy-Filename, X-Aidy-Mime, X-Aidy-Text",
                        ),
                    ],
                )
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

    def _bearer_token(self, headers: dict[str, str]) -> str:
        auth = headers.get("authorization", "").strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return headers.get("x-aidy-token", "").strip()

    async def _http_upload(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
    ) -> None:
        ident = self.resolve_token(self._bearer_token(headers))
        if ident is None:
            body = json.dumps(
                {
                    "ok": False,
                    "error": "Sesión expirada. En el PC: Emparejar → Mostrar código y entra de nuevo.",
                }
            ).encode("utf-8")
            await self._http_response(writer, 401, body, content_type="application/json")
            return
        try:
            length = int(headers.get("content-length") or "0")
        except ValueError:
            length = 0
        if length <= 0:
            body = json.dumps({"ok": False, "error": "archivo vacío"}).encode("utf-8")
            await self._http_response(writer, 400, body, content_type="application/json")
            return
        if length > MAX_ATTACHMENT_BYTES:
            body = json.dumps(
                {"ok": False, "error": "Máximo 15 MB por archivo"}
            ).encode("utf-8")
            await self._http_response(writer, 413, body, content_type="application/json")
            return
        try:
            raw = await asyncio.wait_for(reader.readexactly(length), timeout=180.0)
        except Exception:
            body = json.dumps(
                {"ok": False, "error": "No se pudo recibir el archivo completo"}
            ).encode("utf-8")
            await self._http_response(writer, 400, body, content_type="application/json")
            return

        filename = headers.get("x-aidy-filename") or "archivo"
        mime = headers.get("x-aidy-mime") or "application/octet-stream"
        to_id = headers.get("x-aidy-to") or "*"
        text = headers.get("x-aidy-text") or ""
        # Header values may be latin-1; filenames often need utf-8 recovery.
        try:
            filename = filename.encode("latin-1").decode("utf-8")
        except Exception:
            pass
        try:
            text = text.encode("latin-1").decode("utf-8")
        except Exception:
            pass

        media_b64 = base64.b64encode(raw).decode("ascii")
        result = await self.send_from_mobile(
            ident.node_id,
            ident.display_name,
            to_id,
            text,
            media_b64=media_b64,
            filename=filename,
            mime=mime,
        )
        if isinstance(result.get("message"), dict):
            result["message"] = self._public_message(result["message"])
        status = 200 if result.get("ok") else 400
        await self._http_response(
            writer,
            status,
            json.dumps(result, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )

    async def _serve_media(self, writer: asyncio.StreamWriter, msg_id: str) -> None:
        from urllib.parse import unquote

        key = unquote(msg_id or "").strip()
        path = self._media_index.get(key)
        if path is None or not path.is_file():
            await self._http_response(writer, 404, b"media not found")
            return
        try:
            body = path.read_bytes()
        except OSError:
            await self._http_response(writer, 404, b"media not found")
            return
        import mimetypes

        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        await self._http_response(
            writer,
            200,
            body,
            content_type=ctype,
            extra_headers=[
                ("Content-Disposition", f'inline; filename="{path.name}"'),
            ],
        )

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
                                {
                                    "type": "error",
                                    "error": "Primero envía hello con pin/token y nombre",
                                }
                            ),
                        )
                        continue
                    pin = str(msg.get("pin") or "").strip()
                    resume_token = str(msg.get("token") or "").strip()
                    name = str(msg.get("name") or "").strip()[:40]
                    resume = False
                    ident: MobileIdentity | None = None
                    if resume_token:
                        ident = self.resolve_token(resume_token)
                        if ident is None:
                            await self._ws_send_text(
                                writer,
                                json.dumps(
                                    {
                                        "type": "error",
                                        "error": "Sesión expirada. Entra otra vez con el código del QR.",
                                    }
                                ),
                            )
                            continue
                        if name:
                            ident.display_name = name
                        resume = True
                    else:
                        if len(name) < 2:
                            await self._ws_send_text(
                                writer,
                                json.dumps(
                                    {"type": "error", "error": "Nombre demasiado corto"}
                                ),
                            )
                            continue
                        if not self.check_pin(pin):
                            await self._ws_send_text(
                                writer,
                                json.dumps(
                                    {
                                        "type": "error",
                                        "error": (
                                            "Código incorrecto o expirado. "
                                            "En el PC: Emparejar → Mostrar código."
                                        ),
                                    }
                                ),
                            )
                            continue
                        ident = self._register_identity(name=name)

                    # Replace any previous live socket for this phone.
                    old = self._sessions.get(ident.node_id)
                    if old is not None and old.writer is not writer:
                        try:
                            old.writer.close()
                        except Exception:
                            pass
                    session = MobileSession(
                        node_id=ident.node_id,
                        display_name=ident.display_name,
                        token=ident.token,
                        writer=writer,
                    )
                    self._sessions[ident.node_id] = session
                    peers = self.list_lan_peers()
                    await self._ws_send_text(
                        writer,
                        json.dumps(
                            {
                                "type": "hello_ok",
                                "self_id": ident.node_id,
                                "token": ident.token,
                                "resume": resume,
                                "host_name": self.cfg.display_name,
                                "team_id": self.cfg.team_id,
                                "peers": peers,
                                "history": [] if resume else self._history[-80:],
                            },
                            ensure_ascii=False,
                        ),
                    )
                    LOGGER.info(
                        "mobile %s: %s (%s)",
                        "resumed" if resume else "joined",
                        ident.display_name,
                        ident.node_id,
                    )
                    continue

                if mtype == "send":
                    text = str(msg.get("text") or "").strip()
                    to_id = str(msg.get("to") or "*").strip() or "*"
                    media_b64 = str(msg.get("media_b64") or "").strip()
                    filename = str(msg.get("filename") or "").strip()
                    mime = str(msg.get("mime") or "").strip()
                    if not text and not media_b64:
                        continue
                    result = await self.send_from_mobile(
                        session.node_id,
                        session.display_name,
                        to_id,
                        text,
                        media_b64=media_b64,
                        filename=filename,
                        mime=mime,
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
                current = self._sessions.get(session.node_id)
                if current is not None and current.writer is writer:
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
