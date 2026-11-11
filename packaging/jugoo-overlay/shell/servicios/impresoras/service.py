"""Read/manage local CUPS printers via CLI tools (no network probing)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Sequence

_DEFAULT_RE = re.compile(
    r"(?:system default destination:\s*|destino predeterminado del sistema:\s*)(.+)$",
    re.IGNORECASE,
)
_ACCEPTING_RE = re.compile(
    r"^(\S+)\s+(?:accepting|aceptando)\b",
    re.IGNORECASE,
)
_NOT_ACCEPTING_RE = re.compile(
    r"^(\S+)\s+(?:not accepting|no aceptando)\b",
    re.IGNORECASE,
)
_PRINTER_RE = re.compile(
    r"^(?:printer|la impresora)\s+(\S+)\s+(.+)$",
    re.IGNORECASE,
)
_URI_RE = re.compile(r"^device for (\S+):\s*(.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class PrinterInfo:
    name: str
    enabled: bool
    accepting: bool
    is_default: bool
    state_text: str
    device_uri: str = ""


@dataclass(frozen=True)
class PrintersSnapshot:
    printers: tuple[PrinterInfo, ...]
    default_name: str | None
    error: str | None = None


class PrintersError(RuntimeError):
    """Raised when a printer action cannot be completed."""


def list_printers() -> PrintersSnapshot:
    """Snapshot of local printers. Never raises; errors go into ``error``."""
    if shutil.which("lpstat") is None:
        return PrintersSnapshot(
            printers=(),
            default_name=None,
            error="CUPS no está disponible (falta lpstat).",
        )

    try:
        default_name = _read_default()
        accepting = _read_accepting()
        states = _read_printer_states()
        uris = _read_uris()
    except PrintersError as error:
        return PrintersSnapshot(printers=(), default_name=None, error=str(error))

    names = sorted(set(accepting) | set(states) | set(uris), key=str.casefold)
    printers: list[PrinterInfo] = []
    for name in names:
        enabled, state_text = states.get(name, (True, "Desconocido"))
        printers.append(
            PrinterInfo(
                name=name,
                enabled=enabled,
                accepting=accepting.get(name, True),
                is_default=bool(default_name) and name == default_name,
                state_text=state_text,
                device_uri=uris.get(name, ""),
            )
        )
    return PrintersSnapshot(
        printers=tuple(printers),
        default_name=default_name,
    )


def set_default_printer(name: str) -> None:
    target = str(name or "").strip()
    if not target:
        raise PrintersError("Falta el nombre de la impresora")
    _run(["lpoptions", "-d", target], label="definir impresora predeterminada")


def set_printer_enabled(name: str, enabled: bool) -> None:
    target = str(name or "").strip()
    if not target:
        raise PrintersError("Falta el nombre de la impresora")
    command = "cupsenable" if enabled else "cupsdisable"
    if shutil.which(command) is None:
        raise PrintersError(f"Falta {command} (paquete cups-client)")
    _run([command, target], label=("activar" if enabled else "desactivar") + " impresora")


def cancel_jobs(name: str | None = None) -> None:
    """Cancel jobs for one printer, or all jobs when ``name`` is None."""
    if shutil.which("cancel") is None:
        raise PrintersError("Falta cancel (paquete cups-client)")
    argv = ["cancel", "-a"]
    if name:
        argv.append(str(name).strip())
    _run(argv, label="cancelar trabajos")


def launch_printer_manager() -> None:
    """Open the system printer UI (system-config-printer preferred)."""
    candidates = (
        ["system-config-printer"],
        ["xdg-open", "http://localhost:631/admin"],
    )
    errors: list[str] = []
    for argv in candidates:
        binary = shutil.which(argv[0])
        if binary is None:
            errors.append(f"no está {argv[0]}")
            continue
        try:
            subprocess.Popen(
                [binary, *argv[1:]],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_launch_env(),
            )
            return
        except OSError as error:
            errors.append(str(error))
    detail = "; ".join(errors) if errors else "sin candidatos"
    raise PrintersError(f"No se pudo abrir el gestor de impresoras: {detail}")


def launch_cups_web() -> None:
    if shutil.which("xdg-open") is None:
        raise PrintersError("Falta xdg-open")
    _spawn(["xdg-open", "http://localhost:631"])


def _read_default() -> str | None:
    out = _capture(["lpstat", "-d"])
    for line in out.splitlines():
        match = _DEFAULT_RE.search(line.strip())
        if match:
            name = match.group(1).strip()
            return name or None
    return None


def _read_accepting() -> dict[str, bool]:
    out = _capture(["lpstat", "-a"])
    result: dict[str, bool] = {}
    for line in out.splitlines():
        text = line.strip()
        if not text:
            continue
        match = _ACCEPTING_RE.match(text)
        if match:
            result[match.group(1)] = True
            continue
        match = _NOT_ACCEPTING_RE.match(text)
        if match:
            result[match.group(1)] = False
    return result


def _read_printer_states() -> dict[str, tuple[bool, str]]:
    out = _capture(["lpstat", "-p"])
    result: dict[str, tuple[bool, str]] = {}
    for line in out.splitlines():
        text = line.strip()
        match = _PRINTER_RE.match(text)
        if not match:
            continue
        name = match.group(1)
        rest = match.group(2).strip()
        lowered = rest.casefold()
        enabled = "desactivada" not in lowered and "disabled" not in lowered
        result[name] = (enabled, rest)
    return result


def _read_uris() -> dict[str, str]:
    try:
        out = _capture(["lpstat", "-v"])
    except PrintersError:
        return {}
    result: dict[str, str] = {}
    for line in out.splitlines():
        match = _URI_RE.match(line.strip())
        if match:
            result[match.group(1)] = match.group(2).strip()
    return result


def _capture(argv: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PrintersError(str(error)) from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PrintersError(detail or f"falló {' '.join(argv)}")
    return completed.stdout or ""


def _run(argv: Sequence[str], *, label: str) -> None:
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            timeout=8.0,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PrintersError(f"No se pudo {label}: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PrintersError(detail or f"No se pudo {label}")


def _spawn(argv: Sequence[str]) -> None:
    try:
        subprocess.Popen(
            list(argv),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_launch_env(),
        )
    except OSError as error:
        raise PrintersError(str(error)) from error


def _launch_env() -> dict[str, str]:
    env = dict(os.environ)
    # Prefer Wayland for GTK printer UI when available.
    env.setdefault("GDK_BACKEND", "wayland")
    return env
