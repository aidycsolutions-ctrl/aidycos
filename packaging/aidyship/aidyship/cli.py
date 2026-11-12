"""aidyship CLI."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import add_favorite, load_config
from .gitops import find_git_root, repo_status
from .github_auth import auth_status, logout, setup_git_credentials, start_login_flow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aidyship",
        description="Commit y push rápido a GitHub para AidyCOS",
    )
    parser.add_argument("--version", action="version", version=f"aidyship {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ui", help="Abrir la ventana gráfica")
    sub.add_parser("status", help="Estado de la sesión GitHub")
    sub.add_parser("login", help="Iniciar sesión de GitHub (terminal + navegador)")
    sub.add_parser("logout", help="Cerrar sesión de GitHub")
    p_repo = sub.add_parser("repo", help="Mostrar estado git de una carpeta")
    p_repo.add_argument("path", nargs="?", default=".", help="Ruta del repo")
    p_add = sub.add_parser("add-favorite", help="Añadir un repo a favoritos")
    p_add.add_argument("path", help="Ruta del repo")

    args = parser.parse_args(argv)

    if args.cmd == "ui":
        from .ui import run_ui

        return run_ui()

    if args.cmd == "status":
        session = auth_status()
        if session.logged_in:
            print(f"Conectado como @{session.login}" if session.login else "Conectado a GitHub")
            return 0
        print(session.detail or "Sin sesión de GitHub.", file=sys.stderr)
        return 1

    if args.cmd == "login":
        ok, detail = start_login_flow()
        print(detail)
        return 0 if ok else 1

    if args.cmd == "logout":
        ok, detail = logout()
        print(detail)
        return 0 if ok else 1

    if args.cmd == "repo":
        status = repo_status(args.path)
        if not status.ok:
            print(status.error, file=sys.stderr)
            return 1
        print(f"{status.root}")
        print(f"rama: {status.branch or '?'}  upstream: {status.upstream or '—'}")
        if status.ahead or status.behind:
            print(f"ahead {status.ahead} / behind {status.behind}")
        print(f"cambios: {len(status.files)}")
        for item in status.files:
            print(f"  {item.status} {item.path}")
        return 0

    if args.cmd == "add-favorite":
        root = find_git_root(args.path)
        if root is None:
            print("No es un repositorio git.", file=sys.stderr)
            return 1
        cfg = add_favorite(load_config(), root)
        setup_git_credentials()
        print(f"Favorito: {root}")
        print(f"Total: {len(cfg.favorites)}")
        return 0

    parser.error(f"comando desconocido: {args.cmd}")
    return 2
