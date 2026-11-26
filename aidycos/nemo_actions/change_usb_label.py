#!/usr/bin/env python3
"""Nemo action to safely change a removable filesystem label via UDisks2."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys


SUPPORTED_FILESYSTEMS = {"vfat", "fat", "fat32", "exfat", "ntfs"}
UDISKS_SERVICE = "org.freedesktop.UDisks2"
UDISKS_FILESYSTEM = "org.freedesktop.UDisks2.Filesystem"


class ActionError(RuntimeError):
    pass


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def zenity(*args: str) -> subprocess.CompletedProcess[str]:
    return run(["zenity", *args])


def _message(title: str, message: str, *, error: bool = False) -> None:
    kind = "--error" if error else "--info"
    zenity(kind, "--title", title, "--text", message)


def inspect_device(device: str) -> tuple[str, str]:
    """Return (filesystem, UDisks object path) after conservative device checks."""
    if not device.startswith("/dev/") or not Path(device).is_block_device():
        raise ActionError("No se pudo identificar una partición de almacenamiento válida.")

    result = run([
        "lsblk", "--json", "--paths", "--output",
        "PATH,TYPE,FSTYPE,RM,TRAN,PKNAME", device,
    ])
    if result.returncode != 0:
        raise ActionError("No se pudo consultar el dispositivo USB con lsblk.")
    try:
        rows = json.loads(result.stdout)["blockdevices"]
        row = next(item for item in rows if os.path.realpath(item.get("path", "")) == os.path.realpath(device))
    except (KeyError, StopIteration, TypeError, json.JSONDecodeError) as error:
        raise ActionError("No se pudo leer la información de la partición USB.") from error

    if row.get("type") != "part":
        raise ActionError("Selecciona una partición USB, no el disco completo.")
    filesystem = str(row.get("fstype") or "").lower()
    if filesystem not in SUPPORTED_FILESYSTEMS:
        raise ActionError(
            f"El sistema de archivos {filesystem or 'desconocido'} no está habilitado para cambiar la etiqueta. "
            "Esta acción admite FAT, exFAT y NTFS."
        )

    removable = str(row.get("rm", "0")) == "1" or str(row.get("tran", "")).lower() == "usb"
    parent = row.get("pkname")
    if not removable and parent:
        parent_path = parent if str(parent).startswith("/dev/") else f"/dev/{parent}"
        parent_info = run([
            "lsblk", "--json", "--paths", "--output", "PATH,RM,TRAN", parent_path,
        ])
        if parent_info.returncode == 0:
            try:
                parent_row = json.loads(parent_info.stdout)["blockdevices"][0]
                removable = str(parent_row.get("rm", "0")) == "1" or str(
                    parent_row.get("tran", "")
                ).lower() == "usb"
            except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                pass
    if not removable:
        raise ActionError("Por seguridad, esta acción solo permite unidades extraíbles conectadas por USB.")

    info = run(["udisksctl", "info", "--block-device", device])
    if info.returncode != 0:
        raise ActionError("UDisks2 no pudo identificar esta partición.")
    match = re.search(r"^(/org/freedesktop/UDisks2/block_devices/[A-Za-z0-9_]+):", info.stdout, re.M)
    if not match:
        raise ActionError("UDisks2 no devolvió una ruta de dispositivo válida.")
    return filesystem, match.group(1)


def current_label(device: str) -> str:
    result = run(["lsblk", "--noheadings", "--raw", "--output", "LABEL", device])
    return result.stdout.strip() if result.returncode == 0 else ""


def validate_label(label: str) -> str:
    if not label or label != label.strip() or any(ord(char) < 32 or ord(char) == 127 for char in label):
        raise ActionError("Escribe una etiqueta no vacía, sin espacios al inicio o al final ni caracteres de control.")
    return label


def change_label(device: str, filesystem: str, object_path: str, label: str) -> None:
    validate_label(label)
    if filesystem not in SUPPORTED_FILESYSTEMS:
        raise ActionError(f"Sistema de archivos no habilitado: {filesystem}.")
    if not object_path.startswith("/org/freedesktop/UDisks2/block_devices/"):
        raise ActionError("UDisks2 no devolvió una ruta de partición válida.")

    mounted = run(["findmnt", "--noheadings", "--raw", "--source", device, "--output", "TARGET"])
    was_mounted = mounted.returncode == 0 and bool(mounted.stdout.strip())
    if was_mounted:
        unmount = run(["udisksctl", "unmount", "--block-device", device])
        if unmount.returncode != 0:
            detail = (unmount.stderr or unmount.stdout).strip()
            raise ActionError(
                "No se pudo desmontar la USB. Cierra archivos y ventanas abiertos en esa unidad e inténtalo de nuevo."
                + (f"\n\n{detail}" if detail else "")
            )

    # JSON strings use the same quoted-string escaping accepted by GVariant.
    set_label = run([
        "gdbus", "call", "--system", "--dest", UDISKS_SERVICE,
        "--object-path", object_path,
        "--method", f"{UDISKS_FILESYSTEM}.SetLabel",
        json.dumps(label, ensure_ascii=False), "{}",
    ])

    remount = None
    if was_mounted:
        remount = run(["udisksctl", "mount", "--block-device", device])

    if set_label.returncode != 0:
        detail = (set_label.stderr or set_label.stdout).strip()
        message = "UDisks2 no pudo cambiar la etiqueta. No se formateó ni se borró la USB."
        if remount is not None and remount.returncode != 0:
            message += "\nLa USB quedó desmontada; puedes montarla desde Nemo."
        if detail:
            message += f"\n\n{detail}"
        raise ActionError(message)
    if remount is not None and remount.returncode != 0:
        detail = (remount.stderr or remount.stdout).strip()
        raise ActionError(
            "La etiqueta se cambió, pero la USB no se pudo montar de nuevo. Puedes montarla desde Nemo."
            + (f"\n\n{detail}" if detail else "")
        )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        _message("AidyC Explorer", "Abre la USB en Nemo y haz clic derecho sobre un archivo para cambiar su etiqueta.", error=True)
        return 2
    device = args[0]

    try:
        filesystem, object_path = inspect_device(device)
        old_label = current_label(device)
        entered = zenity(
            "--entry", "--title", "AidyC Explorer — Cambiar etiqueta de USB",
            "--text", f"Nueva etiqueta para la unidad {device} ({filesystem}):",
            "--entry-text", old_label,
        )
        if entered.returncode != 0:
            return 0
        label = entered.stdout.rstrip("\r\n")
        validate_label(label)

        confirmation = zenity(
            "--question", "--title", "Confirmar cambio de etiqueta",
            "--text", f"Se cambiará la etiqueta de «{old_label or device}» a «{label}».\n\n"
            "La operación desmonta temporalmente la USB. No formatea ni elimina archivos. ¿Continuar?",
            "--ok-label", "Cambiar etiqueta", "--cancel-label", "Cancelar",
        )
        if confirmation.returncode != 0:
            return 0
        change_label(device, filesystem, object_path, label)
        _message("AidyC Explorer", f"La etiqueta de la USB ahora es «{label}».")
        return 0
    except ActionError as error:
        _message("No se pudo cambiar la etiqueta", str(error), error=True)
        return 1
    except FileNotFoundError as error:
        _message("Falta una dependencia", f"No se encontró el comando requerido: {error.filename}", error=True)
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
