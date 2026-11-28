"""Read/manage local CUPS printers via CLI tools (no network probing)."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
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
_URI_RE = re.compile(
    r"^(?:device for|dispositivo para)\s+(\S+):\s*(.+)$",
    re.IGNORECASE,
)
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_NETWORK_URI_RE = re.compile(
    r"^(?:ipp|ipps|http|https|socket|lpd|smb|dnssd)://",
    re.IGNORECASE,
)
_LOCAL_URI_RE = re.compile(
    r"^(?:usb|hp|hpfax|parallel|serial|bluetooth|beh):",
    re.IGNORECASE,
)
_LOOPBACK_URI_RE = re.compile(
    r"^(?:ipp|ipps|http|https)://(?:localhost|127\.0\.0\.1|::1)(?::|/|$)",
    re.IGNORECASE,
)
_LINK_LOCAL_URI_RE = re.compile(
    r"^(?:ipp|ipps|http|https|socket)://.*"
    r"(?:%25|\[fe80:|fe80:|169\.254\.)",
    re.IGNORECASE,
)
_HP_NET_URI_RE = re.compile(r"^hp:/net/", re.IGNORECASE)

CATALOG_VERSION = 1
CATALOG_FILENAME = "shared-printers.json"
ESCPOS_QUEUE = "Tickets"
ESCPOS_FILENAME = "escpos.json"

# lpinfo lines that are still the sample text from the docs, not a device.
_PLACEHOLDER_URI_RE = re.compile(
    r"IP-DE-LA-TERMICA|PEGAR-URI|usb://…|usb://\.\.\.",
    re.IGNORECASE,
)
# Thermal / POS printers that speak ESC/POS and own the cash-drawer kick port.
_RECEIPT_NAME_RE = re.compile(
    r"epson|xprinter|star|bixolon|gprinter|rongta|hprt|"
    r"pos-?58|pos-?80|thermal|ticket|tm-t|3nstar|zjiang|sam4s|cashino|snbc",
    re.IGNORECASE,
)
# Office inkjets must stay on their normal driver, never on a raw queue.
_OFFICE_PRINTER_RE = re.compile(
    r"hewlett|smart[-_ %]?tank|\bhp\b|canon|brother|lexmark|xerox|kyocera|ricoh",
    re.IGNORECASE,
)
_ESCPOS_PPD = """*PPD-Adobe: "4.3"
*FormatVersion: "4.3"
*FileVersion: "1.0"
*LanguageVersion: English
*LanguageEncoding: ISOLatin1
*PCFileName: "ESCPOS.PPD"
*Manufacturer: "Generic"
*Product: "(ESC/POS Raw)"
*ModelName: "ESC/POS Raw"
*ShortNickName: "ESC/POS Raw"
*NickName: "ESC/POS Raw"
*PSVersion: "(3010.000) 0"
*LanguageLevel: "3"
*ColorDevice: False
*DefaultColorSpace: Gray
*FileSystem: False
*Throughput: "1"
*LandscapeOrientation: Plus90
*TTRasterizer: Type42
*cupsFilter: "application/vnd.cups-raw 0 -"
*cupsVersion: 2.4
*cupsManualCopies: True
"""


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


@dataclass(frozen=True)
class EscposConfig:
    """Local raw queue for an ESC/POS ticket printer (cash drawer)."""

    queue: str = ESCPOS_QUEUE
    set_default: bool = True
    device_uri: str = ""
    auto_single_usb: bool = True


@dataclass(frozen=True)
class EscposApplyResult:
    queue: str
    device_uri: str
    applied: bool
    default_set: bool
    removed_placeholder: bool
    message: str


class PrintersError(RuntimeError):
    """Raised when a printer action cannot be completed."""


_CUPS_BIN_DIRS = ("/usr/sbin", "/usr/bin", "/sbin", "/bin")


def cups_bin(name: str) -> str:
    """Resolve a CUPS tool even when /usr/sbin is missing from PATH.

    Desktop sessions (and Jugoo) often omit ``/usr/sbin``, so ``lpadmin`` /
    ``cupsctl`` / ``cupsenable`` would otherwise look "missing".
    """
    tool = str(name or "").strip()
    if not tool:
        raise PrintersError("Falta el nombre de la herramienta CUPS")
    found = shutil.which(tool)
    if found:
        return found
    for directory in _CUPS_BIN_DIRS:
        candidate = Path(directory) / tool
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        except OSError:
            continue
    raise PrintersError(f"Falta {tool} (paquete cups-client)")


def list_printers() -> PrintersSnapshot:
    """Snapshot of local printers. Never raises; errors go into ``error``."""
    try:
        cups_bin("lpstat")
    except PrintersError:
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
    _run(
        [cups_bin("lpoptions"), "-d", target],
        label="definir impresora predeterminada",
    )


def set_printer_enabled(name: str, enabled: bool) -> None:
    target = str(name or "").strip()
    if not target:
        raise PrintersError("Falta el nombre de la impresora")
    command = "cupsenable" if enabled else "cupsdisable"
    _run(
        [cups_bin(command), target],
        label=("activar" if enabled else "desactivar") + " impresora",
    )


def cancel_jobs(name: str | None = None) -> None:
    """Cancel jobs for one printer, or all jobs when ``name`` is None."""
    argv = [cups_bin("cancel"), "-a"]
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


def documents_catalog_path() -> Path:
    """User-visible copy under Documentos/Documents for easy sharing."""
    for name in ("Documentos", "Documents"):
        folder = Path.home() / name
        if folder.is_dir():
            return folder / CATALOG_FILENAME
    return Path.home() / CATALOG_FILENAME


def discover_catalog_candidates() -> tuple[Path, ...]:
    """Known locations to try when applying a shared catalog."""
    seen: list[Path] = []
    for candidate in (
        default_catalog_path(),
        documents_catalog_path(),
        Path.home() / CATALOG_FILENAME,
        Path.home() / "Descargas" / CATALOG_FILENAME,
        Path.home() / "Downloads" / CATALOG_FILENAME,
    ):
        resolved = candidate.expanduser()
        if resolved in seen:
            continue
        seen.append(resolved)
    return tuple(seen)


def is_network_uri(uri: str) -> bool:
    text = str(uri or "").strip()
    if not text:
        return False
    if _HP_NET_URI_RE.match(text):
        return True
    return _NETWORK_URI_RE.match(text) is not None


def is_loopback_uri(uri: str) -> bool:
    text = str(uri or "").strip()
    return bool(text) and _LOOPBACK_URI_RE.match(text) is not None


def is_link_local_uri(uri: str) -> bool:
    """True for fe80:: / 169.254 URIs that only work on this host/NIC."""
    text = str(uri or "").strip()
    return bool(text) and _LINK_LOCAL_URI_RE.match(text) is not None


def is_local_uri(uri: str) -> bool:
    text = str(uri or "").strip()
    if not text:
        return False
    if is_loopback_uri(text):
        return True
    if _HP_NET_URI_RE.match(text):
        return False
    return _LOCAL_URI_RE.match(text) is not None


def is_directly_shareable_uri(uri: str) -> bool:
    """True when other LAN PCs can use this URI without this host as a bridge."""
    text = str(uri or "").strip()
    return (
        is_network_uri(text)
        and not is_loopback_uri(text)
        and not is_link_local_uri(text)
    )


def shareable_entries(
    snapshot: PrintersSnapshot | None = None,
    *,
    include_local_via_cups: bool = False,
) -> tuple[SharedPrinterEntry, ...]:
    """Build entries other AidyCOS PCs can import.

    LAN/network URIs are included as-is. Link-local IPv6/APIPA queues reuse a
    previously published portable URI when available. USB/localhost queues are
    only included when ``include_local_via_cups`` is true (after enabling CUPS
    sharing).
    """
    snap = snapshot or list_printers()
    if snap.error:
        raise PrintersError(snap.error)
    host = lan_hostname()
    catalog_uris = _catalog_portable_uris()
    entries: list[SharedPrinterEntry] = []
    for printer in snap.printers:
        uri = (printer.device_uri or "").strip()
        share_uri = uri
        if is_link_local_uri(uri):
            share_uri = catalog_uris.get(printer.name, "")
        if is_directly_shareable_uri(share_uri):
            entries.append(
                SharedPrinterEntry(
                    name=printer.name,
                    device_uri=share_uri,
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


def _catalog_portable_uris() -> dict[str, str]:
    """Map printer name → portable URI from an existing AidyCOS catalog."""
    found: dict[str, str] = {}
    for candidate in discover_catalog_candidates():
        if not candidate.is_file():
            continue
        try:
            catalog = load_share_catalog(candidate)
        except PrintersError:
            continue
        for item in catalog.printers:
            if item.name in found:
                continue
            if is_directly_shareable_uri(item.device_uri):
                found[item.name] = item.device_uri
    return found


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
    payload = json.dumps(catalog_to_dict(catalog), indent=2, ensure_ascii=False) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    return target


def publish_share_catalog(*, include_local_via_cups: bool = False) -> tuple[Path, ...]:
    """One-click publish: write portable URIs for other AidyCOS PCs.

    Also best-effort enables CUPS sharing so USB/localhost queues can be bridged.
    """
    try:
        enable_lan_sharing()
    except PrintersError:
        # Network-only catalogs still publish without CUPS share.
        pass
    primary = export_share_catalog(
        default_catalog_path(),
        include_local_via_cups=include_local_via_cups,
    )
    written = [primary]
    payload = primary.read_text(encoding="utf-8")
    for extra in (
        documents_catalog_path(),
        _packaging_catalog_path(),
    ):
        if extra is None:
            continue
        if extra.resolve() == primary.resolve():
            continue
        try:
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_text(payload, encoding="utf-8")
            written.append(extra)
        except OSError:
            continue
    return tuple(written)


def _packaging_catalog_path() -> Path | None:
    """If this machine has an AidyCOS checkout, keep packaging/printers in sync."""
    candidates: list[Path] = []
    for env_root in (
        os.environ.get("AIDYCOS_ROOT"),
        str(Path.home() / ".local/share/aidycos/src"),
        "/opt/aidyc/aidycos",
    ):
        if env_root:
            candidates.append(Path(env_root) / "packaging/printers" / CATALOG_FILENAME)
    # Walk up from this service file when running from the overlay checkout.
    for parent in Path(__file__).resolve().parents:
        packaging = parent / "packaging" / "printers"
        if packaging.is_dir():
            candidates.append(packaging / CATALOG_FILENAME)
            break
    for path in candidates:
        if path.parent.is_dir():
            return path
    return None


def load_share_catalog(path: Path | str | None = None) -> ShareCatalog:
    target = Path(path) if path else default_catalog_path()
    if not target.is_file():
        raise PrintersError(f"No se encontró el catálogo: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PrintersError(f"No se pudo leer el catálogo: {error}") from error
    return catalog_from_dict(payload)


def resolve_catalog_path(path: Path | str | None = None) -> Path:
    """Return an existing catalog path, searching known locations when needed."""
    if path is not None:
        target = Path(path).expanduser()
        if not target.is_file():
            raise PrintersError(f"No se encontró el catálogo: {target}")
        return target
    for candidate in discover_catalog_candidates():
        if candidate.is_file():
            return candidate
    raise PrintersError(
        "No hay catálogo AidyCOS. En el PC de origen pulsa «Publicar catálogo» "
        "y copia shared-printers.json a este equipo."
    )


def catalog_needs_apply(path: Path | str | None = None) -> bool:
    """True when the shared catalog has printers this PC still lacks/needs fixing."""
    try:
        target = resolve_catalog_path(path)
        data = load_share_catalog(target)
    except PrintersError:
        return False
    existing = {item.name: item for item in list_printers().printers}
    for entry in data.printers:
        current = existing.get(entry.name)
        if current is None:
            return True
        current_uri = (current.device_uri or "").strip()
        if is_link_local_uri(current_uri) or is_loopback_uri(current_uri):
            return True
        if current_uri != entry.device_uri and is_directly_shareable_uri(entry.device_uri):
            return True
    return False


def ensure_shared_printers(path: Path | str | None = None) -> ImportResult | None:
    """Apply the AidyCOS catalog when this PC is missing those printers.

    Returns ``None`` when there is nothing to do (or no catalog).
    """
    if not catalog_needs_apply(path):
        return None
    target = resolve_catalog_path(path)
    return import_share_catalog(target, force=True)


def import_share_catalog(
    path: Path | str | None = None,
    *,
    catalog: ShareCatalog | None = None,
    force: bool = True,
) -> ImportResult:
    """Add printers from an AidyCOS catalog onto this machine.

    ``force=True`` (default) re-applies queues even when the URI already matches,
    so import stays reliable across PCs and after CUPS resets.
    """
    data = catalog or load_share_catalog(resolve_catalog_path(path) if path is None else path)
    existing = {item.name: item for item in list_printers().printers}
    added: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    preferred_default: str | None = None
    errors: list[str] = []

    for entry in data.printers:
        current = existing.get(entry.name)
        same_uri = (
            current is not None
            and (current.device_uri or "").strip() == entry.device_uri
        )
        if same_uri and not force:
            skipped.append(entry.name)
        else:
            try:
                add_or_update_printer(entry.name, entry.device_uri)
                try:
                    set_printer_enabled(entry.name, True)
                except PrintersError:
                    pass
                if current is None:
                    added.append(entry.name)
                elif same_uri:
                    skipped.append(entry.name)
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
            except PrintersError as error:
                errors.append(f"{entry.name}: {error}")
                continue
        if entry.is_default:
            preferred_default = entry.name

    default_set = None
    if preferred_default and preferred_default in existing:
        try:
            set_default_printer(preferred_default)
            default_set = preferred_default
        except PrintersError as error:
            errors.append(f"predeterminada: {error}")

    if errors and not (added or updated or skipped):
        raise PrintersError("; ".join(errors))

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
    lpadmin = cups_bin("lpadmin")

    everywhere = [lpadmin, "-p", target, "-v", uri, "-m", "everywhere", "-E"]
    try:
        _run(everywhere, label=f"añadir impresora «{target}»")
        return
    except PrintersError:
        # Older CUPS / drivers: create the queue without an explicit model.
        _run(
            [lpadmin, "-p", target, "-v", uri, "-E"],
            label=f"añadir impresora «{target}»",
        )


def parse_lpinfo_uris(text: str) -> tuple[str, ...]:
    """Pull real device URIs out of ``lpinfo -v`` (skip bare backend names)."""
    found: list[str] = []
    for raw in text.splitlines():
        parts = raw.strip().split(None, 1)
        if len(parts) != 2:
            continue
        uri = parts[1].strip()
        if "://" not in uri or is_placeholder_uri(uri):
            continue
        found.append(uri)
    return tuple(found)


def is_placeholder_uri(uri: str) -> bool:
    """True for the sample URIs in the docs, which are not devices."""
    text = str(uri or "").strip()
    if not text:
        return False
    if _PLACEHOLDER_URI_RE.search(text):
        return True
    return text.rstrip("/") in {"usb://", "socket://", "parallel://"}


def choose_escpos_uri(
    uris: Sequence[str],
    *,
    explicit: str = "",
    auto_single_usb: bool = True,
) -> str | None:
    """Pick the ticket printer that must receive raw ESC/POS bytes.

    An explicit URI wins. Otherwise a named thermal printer wins. If this PC
    has exactly one USB printer and it is not an office inkjet, that USB
    device is the cashier's ticket printer. Network office queues are ignored.
    """
    chosen = str(explicit or "").strip()
    if chosen:
        if is_placeholder_uri(chosen):
            raise PrintersError(
                f"La URI «{chosen}» es un ejemplo. Usa la línea que imprime lpinfo -v."
            )
        return chosen
    real = [uri.strip() for uri in uris if uri and str(uri).strip() and not is_placeholder_uri(uri)]
    named = [
        uri
        for uri in real
        if _RECEIPT_NAME_RE.search(uri) and not _OFFICE_PRINTER_RE.search(uri)
    ]
    if named:
        return named[0]
    usb = [
        uri
        for uri in real
        if uri.lower().startswith("usb://") and not _OFFICE_PRINTER_RE.search(uri)
    ]
    if auto_single_usb and len(usb) == 1:
        return usb[0]
    return None


def load_escpos_config(*paths: Path | str | None) -> EscposConfig:
    """Merge ESC/POS queue settings. Later files win, except a blank URI."""
    data: dict[str, Any] = {}
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        previous_uri = str(data.get("device_uri") or "").strip()
        data.update(payload)
        if not str(data.get("device_uri") or "").strip() and previous_uri:
            data["device_uri"] = previous_uri
    queue = sanitize_printer_name(str(data.get("queue") or ESCPOS_QUEUE)) or ESCPOS_QUEUE
    return EscposConfig(
        queue=queue,
        set_default=bool(data.get("set_default", True)),
        device_uri=str(data.get("device_uri") or "").strip(),
        auto_single_usb=bool(data.get("auto_single_usb", True)),
    )


def list_lpinfo_uris() -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            [cups_bin("lpinfo"), "-v"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20.0,
        )
    except (OSError, subprocess.TimeoutExpired, PrintersError) as error:
        raise PrintersError(f"No se pudo listar dispositivos de impresión: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PrintersError(detail or "lpinfo -v falló")
    return parse_lpinfo_uris(completed.stdout or "")


def add_raw_printer(name: str, device_uri: str) -> None:
    """Create a CUPS queue that forwards bytes unchanged (ESC/POS drawer kick)."""
    target = sanitize_printer_name(name)
    uri = str(device_uri or "").strip()
    if not target:
        raise PrintersError("Falta el nombre de la cola ESC/POS")
    if not uri or is_placeholder_uri(uri):
        raise PrintersError(f"URI no válida para la cola raw: {uri or '(vacía)'}")
    lpadmin = cups_bin("lpadmin")
    try:
        _run_admin(
            [lpadmin, "-p", target, "-v", uri, "-m", "raw", "-E"],
            label=f"crear cola raw «{target}»",
        )
    except PrintersError:
        ppd = _write_escpos_ppd()
        _run_admin(
            [lpadmin, "-p", target, "-v", uri, "-P", str(ppd), "-E"],
            label=f"crear cola raw «{target}»",
        )
    try:
        set_printer_enabled(target, True)
    except PrintersError:
        pass
    try:
        _run_admin([cups_bin("cupsaccept"), target], label=f"aceptar trabajos en «{target}»")
    except PrintersError:
        pass


def remove_printer(name: str) -> None:
    target = sanitize_printer_name(name)
    if not target:
        return
    _run_admin([cups_bin("lpadmin"), "-x", target], label=f"quitar cola «{target}»")


def ensure_escpos_printer(
    config: EscposConfig | None = None,
    *,
    device_uris: Sequence[str] | None = None,
) -> EscposApplyResult:
    """Point a raw queue at the local ticket printer so ESC p opens the drawer.

    IPP Everywhere (the shared HP queue) filters those bytes. This queue does
    not. When a ticket printer is found it becomes the user default, because
    the cash-drawer helper prints to the default printer.
    """
    cfg = config or EscposConfig()
    uris = tuple(device_uris) if device_uris is not None else list_lpinfo_uris()
    current = {item.name: item for item in list_printers().printers}.get(cfg.queue)
    try:
        uri = choose_escpos_uri(
            uris,
            explicit=cfg.device_uri,
            auto_single_usb=cfg.auto_single_usb,
        )
    except PrintersError:
        if current is not None and is_placeholder_uri(current.device_uri):
            remove_printer(cfg.queue)
            return EscposApplyResult(
                queue=cfg.queue,
                device_uri="",
                applied=False,
                default_set=False,
                removed_placeholder=True,
                message=f"Se quitó la cola «{cfg.queue}» porque apuntaba a una URI de ejemplo.",
            )
        raise
    if uri is None:
        if current is not None and is_placeholder_uri(current.device_uri):
            remove_printer(cfg.queue)
            return EscposApplyResult(
                queue=cfg.queue,
                device_uri="",
                applied=False,
                default_set=False,
                removed_placeholder=True,
                message=(
                    f"Se quitó la cola «{cfg.queue}» (URI de ejemplo) "
                    "y no hay una térmica conectada."
                ),
            )
        return EscposApplyResult(
            queue=cfg.queue,
            device_uri="",
            applied=False,
            default_set=False,
            removed_placeholder=False,
            message=(
                "No hay impresora de tickets en este equipo. La impresora de red sigue igual. "
                "Conecta la térmica y vuelve a aplicar el perfil, o escribe su URI en "
                "~/.local/share/aidycos/escpos.json (device_uri)."
            ),
        )
    add_raw_printer(cfg.queue, uri)
    default_set = False
    if cfg.set_default:
        set_default_printer(cfg.queue)
        default_set = True
    return EscposApplyResult(
        queue=cfg.queue,
        device_uri=uri,
        applied=True,
        default_set=default_set,
        removed_placeholder=bool(current and is_placeholder_uri(current.device_uri)),
        message=(
            f"Cola raw «{cfg.queue}» lista en {uri}. "
            "El comando ESC p del cajón sale sin filtro IPP."
            + (" Quedó como impresora predeterminada." if default_set else "")
        ),
    )


# Roll paper the browser should offer by default: 58 mm wide, 210 mm long.
# PPDs for XP-58 clones ship with 58x65 mm first, so Chromium/Firefox end up
# on a tiny page or fall back to Letter.
_RECEIPT_PAGESIZE_RE = re.compile(
    r"^(?:X\d+MMY210MM|w\d+h595|5[78](?:mm)?x210(?:mm)?)$",
    re.IGNORECASE,
)


def choose_receipt_page_size(lpoptions_text: str) -> tuple[str, bool] | None:
    """Find the 58x210 mm choice in ``lpoptions -l`` output.

    Returns ``(choice, already_default)`` or ``None`` when the PPD has no such
    size (raw queues, office printers).
    """
    for raw in str(lpoptions_text or "").splitlines():
        head, sep, rest = raw.partition(":")
        if not sep or not head.strip().startswith("PageSize/"):
            continue
        for token in rest.split():
            default = token.startswith("*")
            choice = token.lstrip("*")
            if _RECEIPT_PAGESIZE_RE.match(choice):
                return choice, default
    return None


def is_receipt_printer(name: str, device_uri: str = "") -> bool:
    text = f"{name} {device_uri}"
    return bool(_RECEIPT_NAME_RE.search(text)) and not _OFFICE_PRINTER_RE.search(text)


def _read_page_size_options(queue: str) -> str:
    try:
        completed = subprocess.run(
            [cups_bin("lpoptions"), "-p", queue, "-l"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20.0,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PrintersError(f"No se pudieron leer las opciones de «{queue}»: {error}") from error
    return completed.stdout or ""


def ensure_receipt_page_size(queues: Sequence[str] | None = None) -> tuple[str, ...]:
    """Make 58 mm x 210 mm the default paper of every thermal queue.

    Returns the queues that were changed. Queues whose driver has no such
    size are left alone.
    """
    if queues is None:
        names = [
            item.name
            for item in list_printers().printers
            if is_receipt_printer(item.name, item.device_uri)
        ]
    else:
        names = [sanitize_printer_name(item) for item in queues]
    changed: list[str] = []
    for name in names:
        if not name:
            continue
        picked = choose_receipt_page_size(_read_page_size_options(name))
        if picked is None or picked[1]:
            continue
        choice = picked[0]
        _run_admin(
            [
                cups_bin("lpadmin"),
                "-p",
                name,
                "-o",
                f"PageSize={choice}",
                "-o",
                f"PageRegion={choice}",
            ],
            label=f"fijar papel 58x210 en «{name}»",
        )
        changed.append(name)
    return tuple(changed)


def enable_lan_sharing(*, share_printers: Sequence[str] | None = None) -> None:
    """Allow other LAN hosts to use printers attached to this PC."""
    _cupsctl_share_printers(True)
    lpadmin = cups_bin("lpadmin")
    names = [sanitize_printer_name(item) for item in (share_printers or ())]
    if not names:
        snapshot = list_printers()
        names = [
            item.name
            for item in snapshot.printers
            if not is_directly_shareable_uri(item.device_uri)
        ]
    for name in names:
        if not name:
            continue
        _run(
            [lpadmin, "-p", name, "-o", "printer-is-shared=true"],
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
    cupsctl = cups_bin("cupsctl")
    flag = "--share-printers" if enabled else "--no-share-printers"
    try:
        _run([cupsctl, flag], label="activar el compartido CUPS")
        return
    except PrintersError:
        pkexec = shutil.which("pkexec")
        if pkexec is None:
            raise
        _run(
            [pkexec, cupsctl, flag],
            label="activar el compartido CUPS (con privilegios)",
        )


def _read_default() -> str | None:
    out = _capture([cups_bin("lpstat"), "-d"])
    for line in out.splitlines():
        match = _DEFAULT_RE.search(line.strip())
        if match:
            name = match.group(1).strip()
            return name or None
    return None


def _read_accepting() -> dict[str, bool]:
    out = _capture([cups_bin("lpstat"), "-a"])
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
    out = _capture([cups_bin("lpstat"), "-p"])
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
        out = _capture([cups_bin("lpstat"), "-v"])
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


def _run_admin(argv: Sequence[str], *, label: str) -> None:
    """Run a CUPS admin tool, retrying with passwordless sudo when needed."""
    try:
        _run(argv, label=label)
        return
    except PrintersError:
        if not _sudo_noninteractive_ok():
            raise
    _run(["sudo", "-n", *list(argv)], label=label)


def _sudo_noninteractive_ok() -> bool:
    if os.geteuid() == 0:
        return False
    sudo = shutil.which("sudo")
    if not sudo:
        return False
    try:
        completed = subprocess.run(
            [sudo, "-n", "true"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _write_escpos_ppd() -> Path:
    handle = tempfile.NamedTemporaryFile(
        prefix="aidycos-escpos-",
        suffix=".ppd",
        delete=False,
        mode="w",
        encoding="utf-8",
    )
    with handle:
        handle.write(_ESCPOS_PPD)
    return Path(handle.name)


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
