"""Read/manage local CUPS printers via CLI tools (no network probing)."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

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
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_NETWORK_URI_RE = re.compile(
    r"^(?:ipp|ipps|http|https|socket|lpd|smb|dnssd)://",
    re.IGNORECASE,
)
_LOCAL_URI_RE = re.compile(
    r"^(?:usb|hp|hpfax|parallel|serial|bluetooth|beh):",
    re.IGNORECASE,
)

CATALOG_VERSION = 1
CATALOG_FILENAME = "shared-printers.json"


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


@dataclass(frozen=True)
class SharedPrinterEntry:
    name: str
    device_uri: str
    is_default: bool = False
    share_kind: str = "network"  # network | cups-shared


@dataclass(frozen=True)
class ShareCatalog:
    printers: tuple[SharedPrinterEntry, ...]
    source_host: str
    exported_at: str
    version: int = CATALOG_VERSION


@dataclass(frozen=True)
class ImportResult:
    added: tuple[str, ...]
    updated: tuple[str, ...]
    skipped: tuple[str, ...]
    default_set: str | None = None


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


def default_catalog_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "aidycos" / CATALOG_FILENAME


def is_network_uri(uri: str) -> bool:
    text = str(uri or "").strip()
    return bool(text) and _NETWORK_URI_RE.match(text) is not None


def is_local_uri(uri: str) -> bool:
    text = str(uri or "").strip()
    return bool(text) and _LOCAL_URI_RE.match(text) is not None


def shareable_entries(
    snapshot: PrintersSnapshot | None = None,
    *,
    include_local_via_cups: bool = False,
) -> tuple[SharedPrinterEntry, ...]:
    """Build entries other AidyCOS PCs can import.

    Network URIs are included as-is. Local/USB printers are only included when
    ``include_local_via_cups`` is true (after enabling CUPS sharing).
    """
    snap = snapshot or list_printers()
    if snap.error:
        raise PrintersError(snap.error)
    host = lan_hostname()
    entries: list[SharedPrinterEntry] = []
    for printer in snap.printers:
        uri = (printer.device_uri or "").strip()
        if is_network_uri(uri):
            entries.append(
                SharedPrinterEntry(
                    name=printer.name,
                    device_uri=uri,
                    is_default=printer.is_default,
                    share_kind="network",
                )
            )
            continue
        if include_local_via_cups and uri:
            entries.append(
                SharedPrinterEntry(
                    name=printer.name,
                    device_uri=f"ipp://{host}/printers/{printer.name}",
                    is_default=printer.is_default,
                    share_kind="cups-shared",
                )
            )
    return tuple(entries)


def build_share_catalog(
    entries: Sequence[SharedPrinterEntry] | None = None,
    *,
    include_local_via_cups: bool = False,
) -> ShareCatalog:
    selected = (
        tuple(entries)
        if entries is not None
        else shareable_entries(include_local_via_cups=include_local_via_cups)
    )
    if not selected:
        raise PrintersError(
            "No hay impresoras compartibles. Añade una de red (ipp://…) "
            "o activa «Compartir locales en la LAN»."
        )
    return ShareCatalog(
        printers=selected,
        source_host=lan_hostname(),
        exported_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        version=CATALOG_VERSION,
    )


def catalog_to_dict(catalog: ShareCatalog) -> dict[str, Any]:
    return {
        "version": int(catalog.version),
        "source_host": catalog.source_host,
        "exported_at": catalog.exported_at,
        "printers": [
            {
                "name": item.name,
                "device_uri": item.device_uri,
                "is_default": bool(item.is_default),
                "share_kind": item.share_kind,
            }
            for item in catalog.printers
        ],
    }


def catalog_from_dict(payload: Any) -> ShareCatalog:
    if not isinstance(payload, dict):
        raise PrintersError("El catálogo de impresoras no es un objeto JSON")
    version = int(payload.get("version") or CATALOG_VERSION)
    if version > CATALOG_VERSION:
        raise PrintersError(
            f"Catálogo demasiado nuevo (versión {version}); actualiza AidyCOS."
        )
    raw_printers = payload.get("printers")
    if not isinstance(raw_printers, list) or not raw_printers:
        raise PrintersError("El catálogo no incluye impresoras")
    entries: list[SharedPrinterEntry] = []
    for item in raw_printers:
        if not isinstance(item, dict):
            continue
        name = sanitize_printer_name(str(item.get("name") or ""))
        uri = str(item.get("device_uri") or "").strip()
        if not name or not uri:
            continue
        if not is_network_uri(uri):
            raise PrintersError(
                f"La impresora «{name}» no tiene una URI de red válida: {uri}"
            )
        kind = str(item.get("share_kind") or "network").strip() or "network"
        entries.append(
            SharedPrinterEntry(
                name=name,
                device_uri=uri,
                is_default=bool(item.get("is_default")),
                share_kind=kind,
            )
        )
    if not entries:
        raise PrintersError("El catálogo no incluye impresoras válidas")
    return ShareCatalog(
        printers=tuple(entries),
        source_host=str(payload.get("source_host") or "").strip() or "desconocido",
        exported_at=str(payload.get("exported_at") or "").strip(),
        version=version,
    )


def export_share_catalog(
    path: Path | str | None = None,
    *,
    include_local_via_cups: bool = False,
) -> Path:
    """Write a shareable AidyCOS printer catalog and return its path."""
    target = Path(path) if path else default_catalog_path()
    catalog = build_share_catalog(include_local_via_cups=include_local_via_cups)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(catalog_to_dict(catalog), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def load_share_catalog(path: Path | str | None = None) -> ShareCatalog:
    target = Path(path) if path else default_catalog_path()
    if not target.is_file():
        raise PrintersError(f"No se encontró el catálogo: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PrintersError(f"No se pudo leer el catálogo: {error}") from error
    return catalog_from_dict(payload)


def import_share_catalog(
    path: Path | str | None = None,
    *,
    catalog: ShareCatalog | None = None,
) -> ImportResult:
    """Add printers from an AidyCOS catalog onto this machine."""
    data = catalog or load_share_catalog(path)
    existing = {item.name: item for item in list_printers().printers}
    added: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    preferred_default: str | None = None

    for entry in data.printers:
        current = existing.get(entry.name)
        if current is not None and (current.device_uri or "").strip() == entry.device_uri:
            skipped.append(entry.name)
        else:
            add_or_update_printer(entry.name, entry.device_uri)
            if current is None:
                added.append(entry.name)
            else:
                updated.append(entry.name)
            existing[entry.name] = PrinterInfo(
                name=entry.name,
                enabled=True,
                accepting=True,
                is_default=False,
                state_text="importada",
                device_uri=entry.device_uri,
            )
        if entry.is_default:
            preferred_default = entry.name

    default_set = None
    if preferred_default:
        set_default_printer(preferred_default)
        default_set = preferred_default

    return ImportResult(
        added=tuple(added),
        updated=tuple(updated),
        skipped=tuple(skipped),
        default_set=default_set,
    )


def add_or_update_printer(name: str, device_uri: str) -> None:
    """Install a CUPS queue for a network/shared URI (IPP Everywhere preferred)."""
    target = sanitize_printer_name(name)
    uri = str(device_uri or "").strip()
    if not target:
        raise PrintersError("Falta el nombre de la impresora")
    if not is_network_uri(uri):
        raise PrintersError(f"URI no compartible: {uri or '(vacía)'}")
    if shutil.which("lpadmin") is None:
        raise PrintersError("Falta lpadmin (paquete cups-client)")

    everywhere = ["lpadmin", "-p", target, "-v", uri, "-m", "everywhere", "-E"]
    try:
        _run(everywhere, label=f"añadir impresora «{target}»")
        return
    except PrintersError:
        # Older CUPS / drivers: create the queue without an explicit model.
        _run(
            ["lpadmin", "-p", target, "-v", uri, "-E"],
            label=f"añadir impresora «{target}»",
        )


def enable_lan_sharing(*, share_printers: Sequence[str] | None = None) -> None:
    """Allow other LAN hosts to use printers attached to this PC."""
    _cupsctl_share_printers(True)
    names = [sanitize_printer_name(item) for item in (share_printers or ())]
    if not names:
        snapshot = list_printers()
        names = [
            item.name
            for item in snapshot.printers
            if is_local_uri(item.device_uri) or not is_network_uri(item.device_uri)
        ]
    for name in names:
        if not name:
            continue
        _run(
            ["lpadmin", "-p", name, "-o", "printer-is-shared=true"],
            label=f"compartir «{name}» en la LAN",
        )


def lan_hostname() -> str:
    host = (socket.gethostname() or "").strip() or "aidycos-pc"
    if "." in host:
        return host
    return f"{host}.local"


def sanitize_printer_name(name: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", str(name or "").strip())
    return cleaned.strip("._-")


def _cupsctl_share_printers(enabled: bool) -> None:
    if shutil.which("cupsctl") is None:
        raise PrintersError("Falta cupsctl (paquete cups-client)")
    flag = "--share-printers" if enabled else "--no-share-printers"
    try:
        _run(["cupsctl", flag], label="activar el compartido CUPS")
        return
    except PrintersError:
        if shutil.which("pkexec") is None:
            raise
        _run(
            ["pkexec", "cupsctl", flag],
            label="activar el compartido CUPS (con privilegios)",
        )


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
            timeout=20.0,
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
