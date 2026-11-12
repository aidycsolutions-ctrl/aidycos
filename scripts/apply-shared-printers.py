#!/usr/bin/env python3
"""Apply the AidyCOS shared-printers catalog with CUPS (no GUI).

Used by the Debian profile installer and can be run by hand:

  python3 scripts/apply-shared-printers.py
  python3 scripts/apply-shared-printers.py /path/to/shared-printers.json
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
    # Prefer the live Jugoo copy when the overlay is already deployed.
    live = Path("/opt/aidyc/jugoo/shell/servicios/impresoras/service.py")
    if live.is_file():
        service_path = live
    spec = importlib.util.spec_from_file_location("aidycos_printers_service", service_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"No se pudo cargar {service_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    service = _load_service()
    path = Path(argv[1]).expanduser() if len(argv) > 1 else None
    try:
        target = service.resolve_catalog_path(path)
        result = service.import_share_catalog(target, force=True)
    except service.PrintersError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    bits = []
    if result.added:
        bits.append("añadidas=" + ",".join(result.added))
    if result.updated:
        bits.append("actualizadas=" + ",".join(result.updated))
    if result.skipped:
        bits.append("ya_listas=" + ",".join(result.skipped))
    if result.default_set:
        bits.append("predeterminada=" + result.default_set)
    print(f"ok catalog={target}" + ((" " + " ".join(bits)) if bits else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
