#!/usr/bin/env python3
"""Deploy the official Jugoo checkout without replacing unmanaged data."""

from __future__ import annotations

import argparse
import shutil
import tempfile
import uuid
from pathlib import Path

MARKER = ".aidycos-managed"


def deploy(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() and source == destination.resolve():
        raise SystemExit("La fuente y el destino de Jugoo no pueden ser la misma ruta.")
    if not (source / "shell" / "__main__.py").is_file():
        raise SystemExit(f"El checkout fuente no parece Jugoo: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=destination.name + ".aidycos-staging-",
            dir=destination.parent,
        )
    )
    staging.rmdir()
    shutil.copytree(source, staging, symlinks=True)
    (staging / MARKER).write_text("Instalación gestionada por AidyCOS.\n", encoding="utf-8")
    if destination.exists():
        if not (destination / MARKER).is_file():
            legacy = destination.with_name(destination.name + ".aidycos-preserved")
            if legacy.exists():
                shutil.rmtree(staging)
                raise SystemExit(
                    f"El destino no está gestionado y ya existe la copia preservada: {legacy}"
                )
            destination.rename(legacy)
            try:
                staging.rename(destination)
            except OSError:
                legacy.rename(destination)
                raise
            print(f"Se conservó la instalación anterior de Jugoo en {legacy}")
            return

        previous = destination.with_name(
            destination.name + ".aidycos-old-" + uuid.uuid4().hex
        )
        destination.rename(previous)
        try:
            staging.rename(destination)
        except OSError:
            previous.rename(destination)
            raise
        shutil.rmtree(previous)
        return
    staging.rename(destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    deploy(args.source, args.destination)


if __name__ == "__main__":
    main()
