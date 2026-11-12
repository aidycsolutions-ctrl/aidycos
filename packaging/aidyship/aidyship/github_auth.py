"""GitHub session helpers via the official ``gh`` CLI (per-user)."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class GitHubSession:
    logged_in: bool
    login: str = ""
    host: str = "github.com"
    detail: str = ""


def gh_bin() -> str | None:
    return shutil.which("gh")


def _run_gh(args: list[str], *, timeout: float = 20.0) -> subprocess.CompletedProcess[str]:
    binary = gh_bin()
    if not binary:
        return subprocess.CompletedProcess(
            args=["gh", *args],
            returncode=127,
            stdout="",
            stderr="No se encontró el comando gh. Instálalo con: sudo apt install gh",
        )
    env = os.environ.copy()
    env.setdefault("GH_PROMPT_DISABLED", "1")
    env.setdefault("GH_NO_UPDATE_NOTIFIER", "1")
    env.setdefault("CI", "1")
    return subprocess.run(
        [binary, *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def auth_status() -> GitHubSession:
    if not gh_bin():
        return GitHubSession(logged_in=False, detail="Falta el paquete gh (GitHub CLI).")
    # Prefer a cheap token probe; falls back to `auth status` text.
    try:
        who = _run_gh(["api", "user", "--jq", ".login"], timeout=12.0)
    except subprocess.TimeoutExpired:
        who = None
    if who is not None and who.returncode == 0:
        login = (who.stdout or "").strip()
        if login:
            return GitHubSession(logged_in=True, login=login, detail=f"api user={login}")
    try:
        result = _run_gh(["auth", "status", "-h", "github.com"], timeout=12.0)
    except subprocess.TimeoutExpired:
        return GitHubSession(logged_in=False, detail="gh auth status tardó demasiado.")
    text = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if result.returncode != 0:
        return GitHubSession(logged_in=False, detail=text or "Sin sesión de GitHub.")
    login = ""
    for line in text.splitlines():
        lowered = line.lower()
        if "logged in to github.com account" in lowered:
            parts = line.split()
            for idx, part in enumerate(parts):
                if part.lower() == "account" and idx + 1 < len(parts):
                    login = parts[idx + 1].strip()
                    break
        if not login and " as " in lowered and "github.com" in lowered:
            login = line.split(" as ", 1)[1].split()[0].strip()
    return GitHubSession(logged_in=True, login=login or "github", detail=text)


def setup_git_credentials() -> tuple[bool, str]:
    try:
        result = _run_gh(["auth", "setup-git"])
    except subprocess.TimeoutExpired:
        return False, "gh auth setup-git tardó demasiado."
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "No se pudo configurar git.").strip()
    return True, "Credential helper de gh listo."


def logout() -> tuple[bool, str]:
    session = auth_status()
    args = ["auth", "logout", "-h", "github.com"]
    if session.login and session.login != "github":
        args.extend(["-u", session.login])
    try:
        result = _run_gh(args, timeout=30.0)
    except subprocess.TimeoutExpired:
        return False, "gh auth logout tardó demasiado."
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "No se pudo cerrar sesión.").strip()
    return True, "Sesión de GitHub cerrada."


def _terminal_prefixes() -> list[list[str]]:
    mapping = (
        ("foot", ["-e"]),
        ("kitty", []),
        ("alacritty", ["-e"]),
        ("xfce4-terminal", ["-e"]),
        ("gnome-terminal", ["--"]),
        ("x-terminal-emulator", ["-e"]),
    )
    prefixes: list[list[str]] = []
    for name, args in mapping:
        path = shutil.which(name)
        if path:
            prefixes.append([path, *args])
    return prefixes


def start_login_flow() -> tuple[bool, str]:
    """Open a terminal running ``gh auth login`` (browser/device flow)."""
    if not gh_bin():
        return False, "Instala GitHub CLI: sudo apt install gh"
    script = (
        "set -e; "
        "echo 'AidyShip — conectar GitHub'; "
        "echo; "
        "gh auth login -h github.com -p https -w; "
        "gh auth setup-git; "
        "echo; "
        "gh auth status -h github.com || true; "
        "echo; "
        "read -r -p 'Listo. Pulsa Enter para cerrar…' _"
    )
    for prefix in _terminal_prefixes():
        cmd = [*prefix, "bash", "-lc", script]
        try:
            subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True, "Se abrió una terminal para iniciar sesión en GitHub."
        except OSError:
            continue
    try:
        subprocess.Popen(
            [gh_bin() or "gh", "auth", "login", "-h", "github.com", "-p", "https", "-w"],
            start_new_session=True,
        )
        return True, "Se lanzó gh auth login. Completa el flujo en el navegador."
    except OSError as exc:
        return False, f"No se pudo abrir el login: {exc}"
