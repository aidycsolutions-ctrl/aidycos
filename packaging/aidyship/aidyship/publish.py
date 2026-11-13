"""Publicar (commit+push) y Deploy a PythonAnywhere — mismo flujo que AidyCAI."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .gitops import find_git_root, git_bin
from .paths import config_path


@dataclass(frozen=True)
class DeployProfile:
    name: str
    branch: str = "main"
    deploy_user: str = ""
    deploy_host: str = ""
    deploy_path: str = ""
    deploy_script: str = "scripts/deploy-pythonanywhere.sh"

    @property
    def can_deploy(self) -> bool:
        return bool(self.deploy_user and self.deploy_host and self.deploy_path)


@dataclass
class PublishResult:
    committed: bool
    pushed: bool
    deployed: bool
    branch: str
    detail: str


# Defaults mirror AidyCAI config/projects.json for AIDYCWeb.
_BUILTIN: dict[str, DeployProfile] = {
    "aidyc-web": DeployProfile(
        name="AidyC-web",
        branch="main",
        deploy_user=os.environ.get("AIDYSHIP_PA_USER", "angeljoc"),
        deploy_host=os.environ.get("AIDYSHIP_PA_HOST", "ssh.pythonanywhere.com"),
        deploy_path=os.environ.get("AIDYSHIP_PA_PATH", "/home/angeljoc"),
        deploy_script="scripts/deploy-pythonanywhere.sh",
    ),
}


def _remote_slug(repo: Path) -> str:
    binary = git_bin()
    if not binary:
        return ""
    result = subprocess.run(
        [binary, "-C", str(repo), "remote", "get-url", "origin"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20.0,
    )
    if result.returncode != 0:
        return ""
    url = (result.stdout or "").strip().lower()
    url = url.removesuffix(".git")
    if "github.com" in url:
        return url.split("github.com", 1)[1].lstrip("/:").strip("/")
    return url


def _load_overrides() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    raw = data.get("deploy_profiles") or {}
    return raw if isinstance(raw, dict) else {}


def detect_deploy_profile(repo: Path | str) -> DeployProfile | None:
    root = find_git_root(repo)
    if root is None:
        return None
    resolved = str(root.resolve())
    name = root.name.lower().replace("_", "-")
    slug = _remote_slug(root)

    overrides = _load_overrides()
    override = overrides.get(resolved) or overrides.get(root.name) or overrides.get("aidyc-web")
    base: DeployProfile | None = None
    if name in {"aidyc-web", "aidycweb"} or slug.endswith("/aidyc-web") or "aidyc-web" in slug:
        base = _BUILTIN["aidyc-web"]
    if base is None and isinstance(override, dict) and override.get("deploy_host"):
        base = DeployProfile(name=root.name)
    if base is None:
        return None
    if isinstance(override, dict):
        return DeployProfile(
            name=str(override.get("name") or base.name),
            branch=str(override.get("branch") or base.branch),
            deploy_user=str(override.get("deploy_user") or base.deploy_user),
            deploy_host=str(override.get("deploy_host") or base.deploy_host),
            deploy_path=str(override.get("deploy_path") or base.deploy_path),
            deploy_script=str(override.get("deploy_script") or base.deploy_script),
        )
    return base


def _run_git(repo: Path, args: list[str], *, timeout: float = 180.0) -> subprocess.CompletedProcess[str]:
    binary = git_bin()
    if not binary:
        return subprocess.CompletedProcess(args=["git", *args], returncode=127, stdout="", stderr="No se encontró git.")
    return subprocess.run(
        [binary, "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _ssh_deploy(profile: DeployProfile) -> tuple[bool, str]:
    if not profile.can_deploy:
        return False, "Falta configuración de deploy (user/host/path)."
    safe_path = profile.deploy_path.replace("'", "'\\''")
    safe_branch = profile.branch.replace("'", "'\\''")
    safe_script = profile.deploy_script.replace("'", "'\\''")
    remote = (
        "set -e; "
        f"cd '{safe_path}'; "
        "git fetch origin; "
        f"git checkout '{safe_branch}'; "
        f"git pull --ff-only origin '{safe_branch}'; "
        f"if [ -f '{safe_script}' ]; then BRANCH='{safe_branch}' PA_BRANCH='{safe_branch}' bash '{safe_script}'; fi"
    )
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "BatchMode=yes",
                f"{profile.deploy_user}@{profile.deploy_host}",
                remote,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=600.0,
        )
    except subprocess.TimeoutExpired:
        return False, "SSH deploy tardó demasiado."
    except FileNotFoundError:
        return False, "No se encontró el comando ssh."
    text = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if result.returncode != 0:
        return False, text or "SSH deploy falló."
    last = text.splitlines()[-1] if text else "Deploy OK"
    return True, last


def publish_repo(
    repo: Path | str,
    message: str,
    *,
    paths: list[str] | None = None,
    deploy: bool = False,
    profile: DeployProfile | None = None,
) -> PublishResult:
    """Commit (si hay cambios) + push; opcionalmente deploy remoto como AidyCAI."""
    root = find_git_root(repo)
    if root is None:
        return PublishResult(False, False, False, "", "No es un repositorio git.")
    profile = profile or detect_deploy_profile(root)
    branch = (profile.branch if profile else "main") or "main"
    text = (message or "").strip()

    try:
        head = _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"], timeout=20.0)
    except subprocess.TimeoutExpired:
        return PublishResult(False, False, False, branch, "git tardó demasiado.")
    current = (head.stdout or "").strip()
    if current and current != branch:
        return PublishResult(
            False,
            False,
            False,
            current,
            f"La rama actual es '{current}', se espera '{branch}'. Cambia de rama antes de publicar.",
        )

    porcelain = _run_git(root, ["status", "--porcelain=v1"], timeout=45.0)
    if porcelain.returncode != 0:
        return PublishResult(False, False, False, branch, (porcelain.stderr or "git status falló.").strip())
    dirty = bool((porcelain.stdout or "").strip())
    committed = False

    if dirty:
        if not text:
            return PublishResult(False, False, False, branch, "Escribe un mensaje de commit para publicar.")
        selected = [p for p in (paths or []) if p]
        add_args = ["add", "-A"] if not selected else ["add", "--", *selected]
        added = _run_git(root, add_args, timeout=60.0)
        if added.returncode != 0:
            return PublishResult(False, False, False, branch, (added.stderr or "git add falló.").strip())
        staged = _run_git(root, ["diff", "--cached", "--name-only"], timeout=30.0)
        if not (staged.stdout or "").strip():
            return PublishResult(False, False, False, branch, "No quedó nada en el índice para commitear.")
        done = _run_git(root, ["commit", "-m", text], timeout=60.0)
        if done.returncode != 0:
            return PublishResult(False, False, False, branch, (done.stderr or done.stdout or "git commit falló.").strip())
        committed = True

    # Align with remote before/while pushing (same safety idea as AidyCAI).
    _run_git(root, ["fetch", "origin", branch], timeout=120.0)
    pushed = _run_git(root, ["push", "-u", "origin", branch], timeout=180.0)
    if pushed.returncode != 0:
        return PublishResult(
            committed,
            False,
            False,
            branch,
            (pushed.stderr or pushed.stdout or "git push falló.").strip(),
        )

    deployed = False
    detail = "Publicado en GitHub" + (" (con commit)" if committed else " (sin commit nuevo)")
    if deploy:
        if profile is None or not profile.can_deploy:
            return PublishResult(committed, True, False, branch, "Push OK, pero no hay perfil de deploy.")
        ok, ssh_detail = _ssh_deploy(profile)
        if not ok:
            return PublishResult(committed, True, False, branch, f"Push OK. Deploy falló: {ssh_detail}")
        deployed = True
        detail = f"{detail}. Deploy OK: {ssh_detail}"
    return PublishResult(committed, True, deployed, branch, detail)


def deploy_only(repo: Path | str, *, profile: DeployProfile | None = None) -> tuple[bool, str]:
    root = find_git_root(repo)
    if root is None:
        return False, "No es un repositorio git."
    profile = profile or detect_deploy_profile(root)
    if profile is None or not profile.can_deploy:
        return False, "Este repo no tiene deploy configurado (¿AidyC-web?)."
    return _ssh_deploy(profile)
