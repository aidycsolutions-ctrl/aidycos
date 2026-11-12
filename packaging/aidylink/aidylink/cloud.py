"""AidyChat REST bridge — Bearer auth + polling fallback."""

from __future__ import annotations

import json
import logging
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Any, Callable

from .config import CloudConfig, LinkConfig
from .messages import LinkMessage

LOGGER = logging.getLogger(__name__)


class AidyChatBridge:
    """Thin HTTP client for /aidychat/api/* using the signed Bearer cookie value."""

    def __init__(
        self,
        cfg: LinkConfig,
        *,
        on_message: Callable[[LinkMessage], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.on_message = on_message
        self._seen_message_ids: set[int] = set()
        self._self_user_id: int | None = cfg.cloud.peer_user_ids.get("self")

    @property
    def enabled(self) -> bool:
        c = self.cfg.cloud
        return bool(c.enabled and c.base_url and c.bearer_token)

    def _url(self, path: str) -> str:
        base = self.cfg.cloud.base_url.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        if not path.startswith("/aidychat"):
            path = "/aidychat" + path
        return base + path

    def _auth_headers(self) -> dict[str, str]:
        """Send Bearer and a cookie that Flask can rehydrate.

        Some reverse proxies strip ``Authorization``. Prefer a raw cookie when
        the token is cookie-safe (itsdangerous URL-safe alphabet); quote when
        the value contains ``=`` so parsers do not truncate it.
        """
        token = (self.cfg.cloud.bearer_token or "").strip().strip('"')
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        token = token.replace(" ", "+")
        if not token:
            return {}
        headers = {"Authorization": f"Bearer {token}"}
        if all(ch.isalnum() or ch in "-_." for ch in token):
            headers["Cookie"] = f"aidychat_auth={token}"
        else:
            cookie = SimpleCookie()
            cookie["aidychat_auth"] = token
            headers["Cookie"] = cookie["aidychat_auth"].OutputString().split(";", 1)[0]
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._url(path)
        if query:
            url += "?" + urllib.parse.urlencode(query)
        body = None
        headers = {
            **self._auth_headers(),
            "Accept": "application/json",
            "User-Agent": "AidyLink/0.2",
        }
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"AidyChat HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"AidyChat network: {exc.reason}") from exc
        if not raw:
            return {}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    def list_chats(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/chats")
        chats = data.get("chats") if isinstance(data.get("chats"), list) else data.get("data")
        if not isinstance(chats, list):
            chats = data if isinstance(data, list) else []
        return [chat for chat in chats if isinstance(chat, dict)]

    def search_user(self, query: str) -> dict[str, Any]:
        try:
            return self._request("GET", "/api/users/search", query={"q": query})
        except RuntimeError as exc:
            # API returns 404 when nobody matches.
            if "HTTP 404" in str(exc):
                return {"found": False, "users": []}
            raise

    def create_chat(self, other_user_id: int) -> int:
        data = self._request("POST", "/api/chats", data={"user2_id": int(other_user_id)})
        chat_id = data.get("chat_id") or data.get("id")
        if chat_id is None:
            raise RuntimeError(data.get("error") or "AidyChat no devolvió el chat")
        return int(chat_id)

    def get_messages(self, chat_id: int, *, since_id: int = 0) -> dict[str, Any]:
        return self._request(
            "GET", f"/api/chats/{int(chat_id)}/messages", query={"since_id": since_id}
        )

    def send_chat_message(
        self,
        chat_id: int,
        content: str,
        *,
        message_type: str = "text",
        media_url: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/messages",
            data={
                "chat_id": int(chat_id),
                "content": content,
                "message_type": message_type,
                "media_url": media_url,
            },
        )

    def upload_media(self, path: Path, *, file_type: str) -> dict[str, Any]:
        """Upload a user-selected attachment through AidyChat's 50 MB endpoint."""
        path = Path(path)
        size = path.stat().st_size
        if size <= 0 or size > 50 * 1024 * 1024:
            raise ValueError("El archivo debe pesar entre 1 byte y 50 MB")
        boundary = f"----AidyLink{uuid.uuid4().hex}"
        filename = path.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        payload = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8") + path.read_bytes() + (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file_type"\r\n\r\n'
            f"{file_type}\r\n--{boundary}--\r\n"
        ).encode("utf-8")
        req = urllib.request.Request(
            self._url("/api/upload"),
            data=payload,
            headers={
                **self._auth_headers(),
                "Accept": "application/json",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "AidyLink/0.2",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"AidyChat HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"AidyChat network: {exc.reason}") from exc
        if not isinstance(data, dict) or not data.get("success") or not data.get("url"):
            raise RuntimeError(str(data.get("error") if isinstance(data, dict) else "upload inválido"))
        return data

    def download_media(self, media_url: str, destination: Path) -> Path:
        base = self.cfg.cloud.base_url.rstrip("/") + "/"
        url = urljoin(base, str(media_url))
        if (
            urlparse(url).netloc != urlparse(base).netloc
            or urlparse(url).scheme != urlparse(base).scheme
            or urlparse(url).scheme not in ("https", "http")
        ):
            raise ValueError("La URL del archivo no pertenece al servidor AidyChat configurado")
        req = urllib.request.Request(
            url,
            headers={
                **self._auth_headers(),
                "User-Agent": "AidyLink/0.2",
            },
        )
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(req, timeout=45) as response, target.open("wb") as out:
                total = 0
                while chunk := response.read(64 * 1024):
                    total += len(chunk)
                    if total > 50 * 1024 * 1024:
                        raise ValueError("El archivo supera el límite de 50 MB")
                    out.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target

    def start_call(self, chat_id: int, call_type: str = "audio") -> dict[str, Any]:
        return self._request(
            "POST", "/api/calls", data={"chat_id": int(chat_id), "call_type": call_type}
        )

    def call_status(self, call_id: int) -> dict[str, Any]:
        return self._request("GET", f"/api/calls/{int(call_id)}")

    def incoming_call(self) -> dict[str, Any]:
        return self._request("GET", "/api/calls/incoming")

    def accept_call(self, call_id: int) -> dict[str, Any]:
        return self._request("POST", f"/api/calls/{int(call_id)}/accept", data={})

    def hangup_call(self, call_id: int, reason: str = "ended") -> dict[str, Any]:
        return self._request(
            "POST", f"/api/calls/{int(call_id)}/hangup", data={"reason": reason}
        )

    def send_call_signal(self, call_id: int, signal_type: str, payload: Any) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/calls/{int(call_id)}/signal",
            data={"type": signal_type, "payload": payload},
        )

    def get_call_signals(self, call_id: int, *, since_id: int = 0) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/calls/{int(call_id)}/signals",
            query={"since_id": since_id},
        )

    def check_session(self) -> dict[str, Any]:
        return self._request("GET", "/api/check-session")

    def login_aidyc(self, username: str, password: str) -> dict[str, Any]:
        """Sign in with the same AidyC ERP username/password."""
        username = (username or "").strip()
        password = password or ""
        if not username or not password:
            raise RuntimeError("Usuario y contraseña requeridos")
        if not self.cfg.cloud.base_url:
            self.cfg.cloud.base_url = "https://www.aidycsolutions.com"
        # Auth endpoint must work without a prior bearer token.
        previous = self.cfg.cloud.bearer_token
        self.cfg.cloud.bearer_token = ""
        try:
            data = self._request(
                "POST",
                "/api/auth/aidyc",
                data={"username": username, "password": password},
            )
        finally:
            self.cfg.cloud.bearer_token = previous
        if not isinstance(data, dict) or not data.get("success") or not data.get("token"):
            raise RuntimeError(
                str((data or {}).get("error") if isinstance(data, dict) else None)
                or "No se pudo iniciar sesión con AidyC"
            )
        token = str(data["token"]).strip()
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        self.cfg.cloud.bearer_token = token
        self.cfg.cloud.enabled = True
        if user.get("id") is not None:
            self.cfg.cloud.peer_user_ids["self"] = int(user["id"])
            self._self_user_id = int(user["id"])
        return data

    def refresh_self_id(self) -> int | None:
        try:
            data = self.check_session()
        except RuntimeError as exc:
            LOGGER.warning("cloud session: %s", exc)
            return self._self_user_id
        user = data.get("user") if isinstance(data.get("user"), dict) else data
        uid = user.get("id") if isinstance(user, dict) else None
        if uid is not None:
            self._self_user_id = int(uid)
            self.cfg.cloud.peer_user_ids["self"] = self._self_user_id
        return self._self_user_id

    def ensure_chat_with(self, other_user_id: int) -> int | None:
        """Find or create 1:1 chat. Returns chat_id."""
        chats = self._request("GET", "/api/chats")
        items = chats.get("chats") or chats.get("data") or []
        if isinstance(chats, dict) and isinstance(chats.get("chats"), list):
            items = chats["chats"]
        elif not isinstance(items, list):
            items = []
        for chat in items:
            if not isinstance(chat, dict):
                continue
            u1 = chat.get("user1_id") or chat.get("user1")
            u2 = chat.get("user2_id") or chat.get("user2")
            ids = {int(u1)} if u1 is not None else set()
            if u2 is not None:
                ids.add(int(u2))
            # nested other_user shapes
            other = chat.get("other_user") or chat.get("peer") or {}
            if isinstance(other, dict) and other.get("id") is not None:
                ids.add(int(other["id"]))
            if other_user_id in ids and chat.get("id") is not None:
                return int(chat["id"])
        created = self._request("POST", "/api/chats", data={"user2_id": other_user_id})
        chat_id = created.get("chat_id") or created.get("id")
        if chat_id is None and isinstance(created.get("chat"), dict):
            chat_id = created["chat"].get("id")
        return int(chat_id) if chat_id is not None else None

    def send_text(self, other_user_id: int, text: str) -> dict[str, Any]:
        chat_id = self.ensure_chat_with(other_user_id)
        if chat_id is None:
            raise RuntimeError("No se pudo abrir chat AidyChat con ese usuario")
        return self._request(
            "POST",
            "/api/messages",
            data={"chat_id": chat_id, "content": text, "message_type": "text"},
        )

    def poll_once(self) -> list[LinkMessage]:
        """Best-effort unread preview → LinkMessage stubs for notification."""
        if not self.enabled:
            return []
        try:
            status = self._request("GET", "/api/users/new-messages")
        except RuntimeError as exc:
            LOGGER.debug("cloud poll: %s", exc)
            return []
        if not status.get("has_new"):
            return []
        last = status.get("last_message") or {}
        preview = str(last.get("preview") or "")
        sender = str(last.get("sender") or "AidyChat")
        msg = LinkMessage.create(
            from_id=f"cloud:{last.get('chat_id') or 'unknown'}",
            from_name=sender,
            to_id=self.cfg.node_id,
            text=preview or "(nuevo mensaje en AidyChat)",
            team_id=self.cfg.team_id,
            via="cloud",
        )
        return [msg]

    async def poll_loop(self, interval: float, on_batch: Callable[[list[LinkMessage]], None]) -> None:
        import asyncio

        while True:
            if self.enabled:
                batch = await asyncio.to_thread(self.poll_once)
                if batch:
                    on_batch(batch)
            await asyncio.sleep(interval)


def apply_cloud_settings(
    cfg: LinkConfig,
    *,
    base_url: str | None = None,
    token: str | None = None,
    enabled: bool | None = None,
    poll_seconds: float | None = None,
    turn_server: str | None = None,
) -> CloudConfig:
    cloud = cfg.cloud
    if base_url is not None:
        cloud.base_url = base_url.rstrip("/")
    if token is not None:
        cloud.bearer_token = token.strip()
    if poll_seconds is not None:
        cloud.poll_seconds = float(poll_seconds)
    if turn_server is not None:
        cloud.turn_server = turn_server.strip()
    if enabled is None:
        cloud.enabled = bool(cloud.base_url and cloud.bearer_token)
    else:
        cloud.enabled = bool(enabled)
    return cloud


def extract_token_from_set_cookie(headers: Any) -> str:
    """Parse aidychat_auth from a urllib HTTPError/response headers map."""
    raw = ""
    try:
        raw = headers.get("Set-Cookie") or headers.get("set-cookie") or ""
    except Exception:
        raw = ""
    if not raw and hasattr(headers, "get_all"):
        try:
            parts = headers.get_all("Set-Cookie") or []
            raw = ",".join(parts)
        except Exception:
            raw = ""
    for chunk in str(raw).split(","):
        for piece in chunk.split(";"):
            piece = piece.strip()
            if piece.startswith("aidychat_auth="):
                return piece.split("=", 1)[1].strip()
    return ""


def test_cloud_connection(cfg: LinkConfig) -> dict[str, Any]:
    """Validate Bearer against /api/check-session and remember self user id."""
    bridge = AidyChatBridge(cfg)
    if not bridge.enabled:
        return {"ok": False, "error": "cloud deshabilitado (falta base_url o token)"}
    data = bridge.check_session()
    if not data.get("authenticated"):
        return {"ok": False, "error": "token inválido o sesión expirada", "raw": data}
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    uid = user.get("id")
    if uid is not None:
        cfg.cloud.peer_user_ids["self"] = int(uid)
    return {
        "ok": True,
        "user_id": uid,
        "username": user.get("username"),
        "base_url": cfg.cloud.base_url,
    }
