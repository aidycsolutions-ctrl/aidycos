"""Config + sesión (token) de AidyShare. No guarda la contraseña."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import config_path, session_path

DEFAULT_BASE_URL = "https://www.aidycsolutions.com"
DEFAULT_REMOTE_FOLDER = "AidyCOS-Backup"


@dataclass
class ShareConfig:
    base_url: str = DEFAULT_BASE_URL
    username: str = ""
    remote_folder: str = DEFAULT_REMOTE_FOLDER

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "username": self.username,
            "remote_folder": self.remote_folder,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ShareConfig:
        raw = data or {}
        return cls(
            base_url=str(raw.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
            username=str(raw.get("username") or "").strip(),
            remote_folder=str(raw.get("remote_folder") or DEFAULT_REMOTE_FOLDER).strip()
            or DEFAULT_REMOTE_FOLDER,
        )


@dataclass
class ShareSession:
    token: str = ""
    session_id: str = ""
    usuario: str = ""
    nombre: str = ""
    padre: str = ""
    tipo: str = ""
    expires: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.token and self.usuario and self.padre)

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "session_id": self.session_id,
            "usuario": self.usuario,
            "nombre": self.nombre,
            "padre": self.padre,
            "tipo": self.tipo,
            "expires": self.expires,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ShareSession:
        raw = data or {}
        return cls(
            token=str(raw.get("token") or "").strip(),
            session_id=str(raw.get("session_id") or "").strip(),
            usuario=str(raw.get("usuario") or "").strip(),
            nombre=str(raw.get("nombre") or "").strip(),
            padre=str(raw.get("padre") or "").strip(),
            tipo=str(raw.get("tipo") or "").strip(),
            expires=str(raw.get("expires") or "").strip(),
        )


def load_config() -> ShareConfig:
    path = config_path()
    if not path.is_file():
        return ShareConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ShareConfig()
    return ShareConfig.from_dict(data if isinstance(data, dict) else {})


def save_config(cfg: ShareConfig) -> None:
    path = config_path()
    path.write_text(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_session() -> ShareSession:
    path = session_path()
    if not path.is_file():
        return ShareSession()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ShareSession()
    return ShareSession.from_dict(data if isinstance(data, dict) else {})


def save_session(session: ShareSession) -> None:
    path = session_path()
    path.write_text(
        json.dumps(session.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def clear_session() -> None:
    path = session_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
