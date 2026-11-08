"""Download AidyC when the dock button has nothing to launch, and open Synaptic visibly."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

PUBLIC_REPO = "aidycsolutions-ctrl/Aidyc-Updates"
PRIVATE_REPO = "aidycsolutions-ctrl/Aidyc"
_INSTALL_PATHS = (
    Path("/usr/bin/aidyc"),
    Path("/opt/aidyc/AidyC/AidyC"),
)
_TERMINALS = (
    "foot",
    "kitty",
    "alacritty",
    "gnome-terminal",
    "kgx",
    "xfce4-terminal",
    "x-terminal-emulator",
    "xterm",
)
_lock = threading.Lock()
_busy = False


def aidyc_is_installed() -> bool:
    return any(path.is_file() and os.access(path, os.X_OK) for path in _INSTALL_PATHS)


def begin_aidyc_install() -> None:
    """Start a background download. A second click while it runs only notifies."""
    global _busy
    with _lock:
        if _busy:
            _notify("AidyC", "La descarga ya está en curso")
            return
        _busy = True
    threading.Thread(target=_install_worker, name="aidyc-install", daemon=True).start()


def open_synaptic(executor, *, agent_running: bool | None = None, terminal: str | None = None) -> bool:
    """Open Synaptic. Return True when the normal desktop launch must not run.

    ``synaptic-pkexec`` exits immediately when the session has no Polkit agent,
    and Jugoo hides that error. A terminal keeps the password prompt on screen.
    """
    if agent_running if agent_running is not None else _polkit_agent_running():
        return False
    chosen = terminal if terminal is not None else _find_terminal()
    if not chosen:
        _notify(
            "Paquetes",
            "Synaptic no puede pedir la contraseña: falta un agente de Polkit y una terminal",
        )
        return True
    _notify("Paquetes", "Synaptic está pidiendo la contraseña en la terminal")
    executor(_terminal_command(chosen, "sudo", "synaptic"))
    return True


def relaxed_depends(depends: str) -> str:
    """Replace the Debian 12 package ``policykit-1`` with the Debian 13 names."""
    seen: set[str] = set()
    parts: list[str] = []
    for raw in depends.split(","):
        item = raw.strip()
        if not item:
            continue
        name = item.split("|", 1)[0].strip().split()[0]
        if name == "policykit-1":
            for replacement in ("pkexec", "polkitd"):
                if replacement not in seen:
                    seen.add(replacement)
                    parts.append(replacement)
            continue
        if name in seen:
            continue
        seen.add(name)
        parts.append(item)
    return ", ".join(parts)


def _install_worker() -> None:
    note = _ProgressNote()
    try:
        note.update("AidyC", "Buscando el paquete…")
        package = _find_package()
        destination = _cache_dir() / package.name
        note.update("AidyC", "Descargando AidyC…")
        if package.url:
            _download(package.url, destination, note)
        else:
            _gh_download(package, destination)
            note.update("AidyC", "Descarga terminada. Preparando la instalación…")
        if package.sha256:
            actual = _sha256(destination)
            if actual != package.sha256:
                raise RuntimeError("el SHA-256 del paquete no coincide")
        ready = _relax_policykit(destination)
        _install_deb(ready, note)
    except Exception as error:
        print(f"shell: aidyc install: {error}", flush=True)
        note.update("AidyC", f"No se pudo instalar: {error}")
    finally:
        global _busy
        with _lock:
            _busy = False


class _Package:
    def __init__(self, name: str, url: str, sha256: str, repo: str, tag: str) -> None:
        self.name = name
        self.url = url
        self.sha256 = sha256
        self.repo = repo
        self.tag = tag


def _find_package() -> _Package:
    public = _package_from_api(PUBLIC_REPO)
    if public is not None:
        return public
    private = _package_from_gh(PRIVATE_REPO)
    if private is not None:
        return private
    raise RuntimeError(
        "no hay un paquete Linux publicado. "
        "El release público todavía no incluye el .deb"
    )


def _package_from_api(repo: str) -> _Package | None:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "jugoo"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return _package_from_release(repo, payload, require_url=True)


def _package_from_gh(repo: str) -> _Package | None:
    if shutil.which("gh") is None:
        return None
    result = subprocess.run(
        ["gh", "release", "view", "--repo", repo, "--json", "tagName,assets"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return _package_from_release(repo, payload, require_url=False)


def _package_from_release(repo: str, payload: dict, *, require_url: bool) -> _Package | None:
    assets = payload.get("assets") or []
    by_name: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        if isinstance(name, str):
            by_name[name] = str(asset.get("browser_download_url") or asset.get("url") or "")
    names = sorted(name for name in by_name if name.startswith("aidyc_") and name.endswith("_amd64.deb"))
    if not names:
        return None
    name = names[-1]
    url = by_name.get(name, "")
    if require_url and not url:
        return None
    digest = ""
    sidecar = by_name.get(name + ".sha256", "")
    if sidecar:
        digest = _read_sha_url(sidecar)
    tag = str(payload.get("tag_name") or payload.get("tagName") or "")
    return _Package(name, url, digest, repo, tag)


def _read_sha_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "jugoo"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read(128).decode("ascii", "replace")
    except (OSError, urllib.error.URLError):
        return ""
    return text.split()[0].strip() if text.split() else ""


def _download(url: str, destination: Path, note: _ProgressNote) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "jugoo"})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
        total = int(response.headers.get("Content-Length") or 0)
        got = 0
        mark = -1
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            output.write(chunk)
            got += len(chunk)
            if total:
                percent = min(100, got * 100 // total)
                if percent // 10 != mark:
                    mark = percent // 10
                    note.update("AidyC", f"Descargando AidyC… {percent}%")
    partial.replace(destination)


def _gh_download(package: _Package, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tag = package.tag or "latest"
    result = subprocess.run(
        [
            "gh", "release", "download", tag,
            "--repo", package.repo,
            "--pattern", package.name,
            "--dir", str(destination.parent),
            "--clobber",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not destination.is_file():
        detail = (result.stderr or result.stdout or "gh no pudo bajar el paquete").strip()
        raise RuntimeError(detail.splitlines()[-1])


def _relax_policykit(deb_path: Path) -> Path:
    if shutil.which("dpkg-deb") is None:
        return deb_path
    depends = subprocess.run(
        ["dpkg-deb", "-f", str(deb_path), "Depends"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if "policykit-1" not in depends or not _policykit_legacy_missing():
        return deb_path
    updated = relaxed_depends(depends)
    with tempfile.TemporaryDirectory(prefix="aidyc-deb-") as raw:
        root = Path(raw)
        extracted = subprocess.run(
            ["dpkg-deb", "-R", str(deb_path), str(root)],
            check=False,
            capture_output=True,
            text=True,
        )
        control_path = root / "DEBIAN" / "control"
        if extracted.returncode != 0 or not control_path.is_file():
            return deb_path
        lines = []
        for line in control_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("Depends:"):
                lines.append(f"Depends: {updated}")
            else:
                lines.append(line)
        control_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rebuilt = deb_path.with_name(deb_path.stem + "-debian13.deb")
        built = subprocess.run(
            ["dpkg-deb", "--root-owner-group", "-b", str(root), str(rebuilt)],
            check=False,
            capture_output=True,
            text=True,
        )
        if built.returncode != 0 or not rebuilt.is_file():
            return deb_path
        return rebuilt


def _policykit_legacy_missing() -> bool:
    result = subprocess.run(
        ["apt-cache", "policy", "policykit-1"],
        check=False,
        capture_output=True,
        text=True,
    )
    text = result.stdout.casefold()
    return "(none)" in text or "(ninguno)" in text


def _install_deb(deb_path: Path, note: _ProgressNote) -> None:
    if _polkit_agent_running() and shutil.which("pkexec"):
        note.update("AidyC", "Instalando AidyC…")
        result = subprocess.run(
            ["pkexec", "apt-get", "install", "-y", str(deb_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "apt no pudo instalar el paquete").strip()
            raise RuntimeError(detail.splitlines()[-1])
        note.update("AidyC", _installed_message(deb_path))
        return
    terminal = _find_terminal()
    if terminal is None:
        raise RuntimeError("falta una terminal para pedir la contraseña de instalación")
    note.update("AidyC", "Escribe tu contraseña en la terminal para terminar de instalar AidyC")
    command = _terminal_command(terminal, "sudo", "apt-get", "install", "-y", str(deb_path))
    subprocess.Popen(list(command), start_new_session=True)


def _installed_message(deb_path: Path) -> str:
    version = ""
    if shutil.which("dpkg-deb"):
        result = subprocess.run(
            ["dpkg-deb", "-f", str(deb_path), "Version"],
            check=False,
            capture_output=True,
            text=True,
        )
        version = result.stdout.strip()
    if version.startswith("33.3"):
        return (
            "AidyC 33.3 instalado. Esta compilación se cierra al abrir el login; "
            "la siguiente debería abrir"
        )
    return "AidyC instalado. Pulsa el botón otra vez para abrirlo"


def _terminal_command(terminal: str, *args: str) -> tuple[str, ...]:
    name = Path(terminal).name
    if name in {"gnome-terminal", "kgx"}:
        return (terminal, "--", *args)
    # -e solo toma el siguiente argumento; el resto lo interpreta como opciones.
    if name == "xfce4-terminal":
        return (terminal, "-x", *args)
    if name == "x-terminal-emulator":
        return (terminal, "-e", " ".join(shlex.quote(arg) for arg in args))
    if name in {"alacritty", "wezterm", "xterm", "uxterm"}:
        return (terminal, "-e", *args)
    return (terminal, *args)


def _find_terminal() -> str | None:
    for name in _TERMINALS:
        found = shutil.which(name)
        if found:
            return found
    return None


def _polkit_agent_running() -> bool:
    uid = str(os.getuid())
    names = (
        "hyprpolkitagent",
        "polkit-gnome-authentication-agent-1",
        "polkit-kde-authentication-agent-1",
    )
    for name in names:
        result = subprocess.run(
            ["pgrep", "-u", uid, "-x", name],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True
    return False


def _cache_dir() -> Path:
    path = Path.home() / ".cache" / "jugoo" / "aidyc-install"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class _ProgressNote:
    def __init__(self) -> None:
        self._id: int | None = None

    def update(self, summary: str, body: str) -> None:
        self._id = _notify(summary, body, replace_id=self._id)


def _notify(summary: str, body: str, *, replace_id: int | None = None) -> int | None:
    notify = shutil.which("notify-send")
    if notify is None:
        print(f"shell: {summary}: {body}", flush=True)
        return replace_id
    command = [notify, "-a", "AidyC", "-i", "aidyc", summary, body, "-t", "12000"]
    if replace_id:
        command.extend(["--replace-id", str(replace_id)])
    command.append("--print-id")
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    text = result.stdout.strip()
    if text.isdigit():
        return int(text)
    return replace_id
