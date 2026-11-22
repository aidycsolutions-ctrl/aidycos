"""Cliente HTTP para login AidyC + AidyCShare (sharecool)."""

from __future__ import annotations

import json
import mimetypes
import socket
import ssl
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

from .config import ShareConfig, ShareSession


@dataclass
class ApiError(Exception):
    message: str
    status: int = 0
    payload: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


@dataclass
class ActiveSessionConflict(ApiError):
    session_info: dict[str, Any] | None = None


class ShareClient:
    def __init__(self, cfg: ShareConfig, session: ShareSession | None = None) -> None:
        self.cfg = cfg
        self.session = session or ShareSession()
        self.timeout = 90.0

    def _url(self, path: str) -> str:
        return urljoin(self.cfg.base_url.rstrip("/") + "/", path.lstrip("/"))

    def _headers(self, *, json_body: bool = False, multipart: bool = False) -> dict[str, str]:
        headers = {
            "User-Agent": "AidyShare/0.1 (AidyCOS)",
            "Accept": "application/json",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.session.token:
            headers["Authorization"] = f"Bearer {self.session.token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, Any]:
        req = Request(self._url(path), data=data, method=method.upper())
        for key, value in (headers or self._headers()).items():
            req.add_header(key, value)
        try:
            with urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read()
                status = getattr(resp, "status", 200) or 200
        except HTTPError as exc:
            raw = exc.read() if exc.fp else b""
            status = exc.code
            payload = _decode_json(raw)
            message = ""
            if isinstance(payload, dict):
                message = str(payload.get("error") or payload.get("mensaje") or "")
            raise ApiError(message or f"HTTP {status}", status=status, payload=payload if isinstance(payload, dict) else None) from exc
        except (URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
            raise ApiError(f"Sin conexión: {exc}") from exc
        payload = _decode_json(raw)
        return status, payload

    def login(
        self,
        username: str,
        password: str,
        *,
        force_login: bool = False,
        session_id_to_kick: str | None = None,
        remember: bool = True,
    ) -> ShareSession:
        payload: dict[str, Any] = {
            "Usuario": username.strip(),
            "Contraseña": password,
            "Remember": bool(remember),
            "force_login": bool(force_login),
            "pc_id": socket.gethostname() or "aidycos",
        }
        if session_id_to_kick:
            payload["session_id_to_kick"] = session_id_to_kick
        body = json.dumps(payload).encode("utf-8")
        try:
            status, data = self._request(
                "POST",
                "/loginU2",
                data=body,
                headers=self._headers(json_body=True),
            )
        except ApiError as exc:
            if exc.status == 409 and isinstance(exc.payload, dict):
                info = exc.payload.get("session_info") if isinstance(exc.payload.get("session_info"), dict) else {}
                raise ActiveSessionConflict(
                    exc.payload.get("mensaje") or "Sesión activa en otro dispositivo",
                    status=409,
                    payload=exc.payload,
                    session_info=info,
                ) from exc
            raise

        if not isinstance(data, dict) or not data.get("success"):
            raise ApiError(
                str((data or {}).get("error") or (data or {}).get("mensaje") or "Login falló"),
                status=status,
                payload=data if isinstance(data, dict) else None,
            )
        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        token = str(inner.get("token") or "").strip()
        if not token:
            raise ApiError("El servidor no devolvió token JWT")
        self.session = ShareSession(
            token=token,
            session_id=str(data.get("session_id") or "").strip(),
            usuario=str(inner.get("usuario") or username).strip(),
            nombre=str(inner.get("nombre") or "").strip(),
            padre=str(inner.get("padre") or "").strip(),
            tipo=str(inner.get("tipo") or "").strip(),
            expires=str(inner.get("expires") or "").strip(),
        )
        return self.session

    def quota(self) -> dict[str, Any]:
        _status, data = self._request("GET", "/api/sharecool/quota", headers=self._headers())
        if not isinstance(data, dict):
            raise ApiError("Respuesta de cuota inválida")
        return data

    def list_dir(self, path: str = "", *, q: str = "", recursive: bool = False) -> dict[str, Any]:
        query = urlencode(
            {
                "path": path or "",
                "q": q or "",
                "recursive": "1" if recursive else "0",
            }
        )
        _status, data = self._request("GET", f"/api/sharecool/list?{query}", headers=self._headers())
        if not isinstance(data, dict):
            raise ApiError("Respuesta de listado inválida")
        return data

    def mkdir(self, path: str, name: str) -> dict[str, Any]:
        body = json.dumps({"path": path or "", "name": name}).encode("utf-8")
        _status, data = self._request(
            "POST",
            "/api/sharecool/mkdir",
            data=body,
            headers=self._headers(json_body=True),
        )
        if not isinstance(data, dict) or not data.get("ok"):
            raise ApiError(str((data or {}).get("error") or "No se pudo crear la carpeta"))
        return data

    def ensure_folder(self, path: str) -> None:
        """Crea ``path`` (relativo) si no existe, carpeta a carpeta."""
        parts = [p for p in (path or "").replace("\\", "/").split("/") if p and p != "."]
        current = ""
        for part in parts:
            parent = current
            listing = self.list_dir(parent)
            names = {item.get("name") for item in (listing.get("items") or []) if isinstance(item, dict)}
            if part not in names:
                self.mkdir(parent, part)
            current = f"{current}/{part}".strip("/") if current else part

    def upload_file(self, local: Path, remote_dir: str = "") -> dict[str, Any]:
        local = Path(local)
        if not local.is_file():
            raise ApiError(f"No es un archivo: {local}")
        boundary = f"----AidyShare{uuid.uuid4().hex}"
        filename = local.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        file_bytes = local.read_bytes()
        chunks: list[bytes] = []
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="path"\r\n\r\n{remote_dir or ""}\r\n'.encode()
        )
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            (
                f'Content-Disposition: form-data; name="archivo"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
        )
        chunks.append(file_bytes)
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        body = b"".join(chunks)
        headers = self._headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        _status, data = self._request(
            "POST",
            "/api/sharecool/upload",
            data=body,
            headers=headers,
            timeout=max(120.0, self.timeout),
        )
        if not isinstance(data, dict) or not data.get("ok"):
            raise ApiError(str((data or {}).get("error") or "Upload falló"))
        return data

    def delete_paths(self, paths: list[str]) -> dict[str, Any]:
        body = json.dumps({"paths": paths}).encode("utf-8")
        _status, data = self._request(
            "POST",
            "/api/sharecool/delete",
            data=body,
            headers=self._headers(json_body=True),
        )
        if not isinstance(data, dict) or not data.get("ok"):
            raise ApiError(str((data or {}).get("error") or "No se pudo borrar"))
        return data

    def download_url(self, remote_path: str) -> str:
        query = urlencode({"path": remote_path, "download": "1"})
        return self._url(f"/api/sharecool/download?{query}")

    def download_file(self, remote_path: str, dest: Path) -> Path:
        dest = Path(dest)
        url = self.download_url(remote_path)
        req = Request(url, method="GET")
        for key, value in self._headers().items():
            req.add_header(key, value)
        try:
            with urlopen(req, timeout=max(120.0, self.timeout)) as resp:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(resp.read())
        except HTTPError as exc:
            raw = exc.read() if exc.fp else b""
            payload = _decode_json(raw)
            msg = ""
            if isinstance(payload, dict):
                msg = str(payload.get("error") or "")
            raise ApiError(msg or f"Download HTTP {exc.code}", status=exc.code) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            raise ApiError(f"Sin conexión: {exc}") from exc
        return dest


def _decode_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def quote_path(path: str) -> str:
    return quote(path or "", safe="/")
