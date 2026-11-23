#!/usr/bin/env python3
"""Create the raw Tickets queue so an ESC/POS cash-drawer pulse is not filtered.

  python3 scripts/apply-escpos-printer.py
  python3 scripts/apply-escpos-printer.py /path/to/escpos.json

When a ticket printer is plugged in, the queue is named Tickets, speaks raw
ESC/POS, and becomes the user default. The shared HP queue is left in place
for normal printing on machines with no thermal printer.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_service():
    root = Path(__file__).resolve().parents[1]
    service_path = (
        root
        / "packaging"
        / "jugoo-overlay"
        / "shell"
        / "servicios"
        / "impresoras"
        / "service.py"
    )
    spec = importlib.util.spec_from_file_location("aidycos_printers_service", service_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"No se pudo cargar {service_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    service = _load_service()
    root = Path(__file__).resolve().parents[1]
    repo_config = root / "packaging" / "printers" / "escpos.json"
    user_config = Path.home() / ".local" / "share" / "aidycos" / "escpos.json"
    paths: list[Path] = [repo_config, user_config]
    if len(argv) > 1:
        paths.append(Path(argv[1]).expanduser())
    config = service.load_escpos_config(*paths)
    try:
        result = service.ensure_escpos_printer(config)
    except service.PrintersError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
