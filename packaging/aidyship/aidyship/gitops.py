"""Thin git wrappers for AidyShip status/commit/push/pull."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str  # porcelain XY code, e.g. " M", "??", "A "


@dataclass
class RepoStatus:
    root: Path
    branch: str = ""
    upstream: str = ""
    ahead: int = 0
    behind: int = 0
    files: list[ChangedFile] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def git_bin() -> str | None:
    return shutil.which("git")


def _run_git(
    repo: Path,
    args: list[str],
    *,
    timeout: float = 120.0,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    binary = git_bin()
    if not binary:
        return subprocess.CompletedProcess(
            args=["git", *args],
            returncode=127,
            stdout="",
            stderr="No se encontró git.",
        )
    return subprocess.run(
        [binary, "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def find_git_root(path: Path | str) -> Path | None:
    start = Path(path).expanduser().resolve()
    if not start.exists():
        return None
    probe = start if start.is_dir() else start.parent
    result = _run_git(probe, ["rev-parse", "--show-toplevel"], timeout=20.0)
    if result.returncode != 0:
        return None
    root = (result.stdout or "").strip()
    return Path(root) if root else None


def repo_status(repo: Path | str) -> RepoStatus:
    root = find_git_root(repo)
    if root is None:
        return RepoStatus(root=Path(repo), error="No es un repositorio git.")
    if not git_bin():
        return RepoStatus(root=root, error="Instala git.")

    branch = ""
    upstream = ""
    ahead = 0
    behind = 0
    files: list[ChangedFile] = []

    try:
        head = _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"], timeout=20.0)
        if head.returncode == 0:
            branch = (head.stdout or "").strip()

        porcelain = _run_git(
            root,
            ["status", "--porcelain=v1", "--branch", "--untracked-files=all"],
            timeout=45.0,
        )
        if porcelain.returncode != 0:
            return RepoStatus(
                root=root,
                branch=branch,
                error=(porcelain.stderr or porcelain.stdout or "git status falló.").strip(),
            )

        for raw in (porcelain.stdout or "").splitlines():
            if raw.startswith("## "):
                meta = raw[3:].strip()
                # ## main...origin/main [ahead 1, behind 2]
                branch_part = meta.split("...", 1)[0].strip()
                if branch_part and branch_part != "HEAD (no branch)":
                    branch = branch_part
                if "..." in meta:
                    rest = meta.split("...", 1)[1]
                    upstream = rest.split(" ", 1)[0].strip()
                    if "[" in meta and "]" in meta:
                        bracket = meta[meta.index("[") + 1 : meta.index("]")]
                        for token in bracket.split(","):
                            token = token.strip()
                            if token.startswith("ahead "):
                                try:
                                    ahead = int(token.split()[1])
                                except (IndexError, ValueError):
                                    ahead = 0
                            elif token.startswith("behind "):
                                try:
                                    behind = int(token.split()[1])
                                except (IndexError, ValueError):
                                    behind = 0
                continue
            if len(raw) < 4:
                continue
            code = raw[:2]
            path = raw[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            files.append(ChangedFile(path=path, status=code))
    except subprocess.TimeoutExpired:
        return RepoStatus(root=root, branch=branch, error="git status tardó demasiado.")

    return RepoStatus(
        root=root,
        branch=branch,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        files=files,
    )


def stage_paths(repo: Path, paths: list[str]) -> tuple[bool, str]:
    if not paths:
        return False, "No hay archivos seleccionados."
    try:
        result = _run_git(repo, ["add", "--", *paths], timeout=60.0)
    except subprocess.TimeoutExpired:
        return False, "git add tardó demasiado."
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "git add falló.").strip()
    return True, f"En índice: {len(paths)} archivo(s)."


def commit(repo: Path, message: str) -> tuple[bool, str]:
    text = (message or "").strip()
    if not text:
        return False, "Escribe un mensaje de commit."
    # Ensure something is staged.
    staged = _run_git(repo, ["diff", "--cached", "--name-only"], timeout=30.0)
    if staged.returncode != 0:
        return False, (staged.stderr or "No se pudo leer el índice.").strip()
    if not (staged.stdout or "").strip():
        return False, "No hay cambios en el índice. Marca archivos y vuelve a intentarlo."
    try:
        result = _run_git(repo, ["commit", "-m", text], timeout=60.0)
    except subprocess.TimeoutExpired:
        return False, "git commit tardó demasiado."
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "git commit falló.").strip()
    summary = (result.stdout or result.stderr or "Commit creado.").strip()
    return True, summary.splitlines()[0] if summary else "Commit creado."


def push(repo: Path) -> tuple[bool, str]:
    try:
        result = _run_git(repo, ["push", "-u", "origin", "HEAD"], timeout=180.0)
    except subprocess.TimeoutExpired:
        return False, "git push tardó demasiado."
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "git push falló.").strip()
    text = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    return True, text.splitlines()[-1] if text else "Push completado."


def pull(repo: Path) -> tuple[bool, str]:
    try:
        result = _run_git(repo, ["pull", "--ff-only"], timeout=180.0)
    except subprocess.TimeoutExpired:
        return False, "git pull tardó demasiado."
    if result.returncode != 0:
        # Fallback without --ff-only for repos that need merge; still keep it simple.
        try:
            result = _run_git(repo, ["pull"], timeout=180.0)
        except subprocess.TimeoutExpired:
            return False, "git pull tardó demasiado."
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "git pull falló.").strip()
    text = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    return True, text.splitlines()[-1] if text else "Pull completado."


def short_diff(repo: Path, path: str, *, max_lines: int = 80) -> str:
    try:
        result = _run_git(
            repo,
            ["diff", "--", path],
            timeout=30.0,
        )
    except subprocess.TimeoutExpired:
        return "Diff tardó demasiado."
    if result.returncode != 0:
        return (result.stderr or "No se pudo obtener el diff.").strip()
    text = result.stdout or ""
    if not text.strip():
        # Untracked or staged-only
        cached = _run_git(repo, ["diff", "--cached", "--", path], timeout=30.0)
        text = cached.stdout or ""
    if not text.strip():
        untracked = repo / path
        if untracked.is_file():
            try:
                content = untracked.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return f"(sin diff) {exc}"
            lines = content.splitlines()
            preview = "\n".join(lines[:max_lines])
            more = "\n…" if len(lines) > max_lines else ""
            return f"(archivo nuevo)\n{preview}{more}"
        return "(sin cambios en el diff)"
    lines = text.splitlines()
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + "\n…"
    return text
