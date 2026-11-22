"""aidyshare CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .api import ActiveSessionConflict, ApiError, ShareClient
from .config import clear_session, load_config, load_session, save_config, save_session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aidyshare",
        description="Respaldo sencillo a AidyCShare del negocio (login AidyC)",
    )
    parser.add_argument("--version", action="version", version=f"aidyshare {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ui", help="Abrir la ventana gráfica")
    p_login = sub.add_parser("login", help="Iniciar sesión AidyC (guarda JWT, no la contraseña)")
    p_login.add_argument("--user", required=True)
    p_login.add_argument("--password", required=True)
    p_login.add_argument("--force", action="store_true", help="Forzar si hay sesión en otro dispositivo")
    sub.add_parser("logout", help="Borrar sesión local")
    sub.add_parser("status", help="Mostrar sesión y cuota")
    p_ls = sub.add_parser("ls", help="Listar carpeta remota")
    p_ls.add_argument("path", nargs="?", default="", help="Ruta remota relativa")
    p_up = sub.add_parser("upload", help="Subir archivo(s) a la carpeta de respaldo")
    p_up.add_argument("files", nargs="+", help="Archivos locales")
    p_up.add_argument("--dir", default="", help="Carpeta remota (default: AidyCOS-Backup)")

    args = parser.parse_args(argv)

    if args.cmd == "ui":
        from .ui import run_ui

        return run_ui()

    cfg = load_config()
    session = load_session()
    client = ShareClient(cfg, session)

    if args.cmd == "login":
        try:
            session = client.login(args.user, args.password, force_login=bool(args.force))
        except ActiveSessionConflict as exc:
            print(exc.message, file=sys.stderr)
            print("Reintenta con --force si quieres entrar aquí.", file=sys.stderr)
            return 409
        except ApiError as exc:
            print(exc.message, file=sys.stderr)
            return 1
        cfg.username = session.usuario
        save_config(cfg)
        save_session(session)
        print(f"OK @{session.usuario} · negocio {session.padre}")
        return 0

    if args.cmd == "logout":
        clear_session()
        print("Sesión local borrada.")
        return 0

    if args.cmd == "status":
        if not session.ok:
            print("Sin sesión. Usa: aidyshare login --user … --password …", file=sys.stderr)
            return 1
        print(f"usuario: {session.usuario} ({session.nombre or '—'})")
        print(f"negocio: {session.padre}")
        try:
            quota = client.quota()
            print(
                f"cuota: {quota.get('usado_mb')} / {quota.get('limite_mb')} MB "
                f"({quota.get('porcentaje')}%)"
            )
        except ApiError as exc:
            print(f"cuota: error — {exc.message}", file=sys.stderr)
            return 1
        return 0

    if args.cmd == "ls":
        if not session.ok:
            print("Sin sesión.", file=sys.stderr)
            return 1
        try:
            data = client.list_dir(args.path or "")
        except ApiError as exc:
            print(exc.message, file=sys.stderr)
            return 1
        for item in data.get("items") or []:
            kind = "DIR " if item.get("type") == "dir" else "FILE"
            print(f"{kind}  {item.get('path')}")
        return 0

    if args.cmd == "upload":
        if not session.ok:
            print("Sin sesión.", file=sys.stderr)
            return 1
        remote = (args.dir or cfg.remote_folder or "AidyCOS-Backup").strip("/")
        try:
            client.ensure_folder(remote)
            for raw in args.files:
                path = Path(raw).expanduser()
                result = client.upload_file(path, remote)
                item = result.get("item") or {}
                print(f"OK {path.name} → {item.get('path') or remote}")
        except ApiError as exc:
            print(exc.message, file=sys.stderr)
            return 1
        return 0

    parser.error(f"comando desconocido: {args.cmd}")
    return 2
