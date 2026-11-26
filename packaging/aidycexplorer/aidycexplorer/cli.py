"""aidycexplorer CLI."""

from __future__ import annotations

import argparse
import sys

from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aidycexplorer",
        description="Explorador de archivos de AidyCOS",
    )
    parser.add_argument("--version", action="version", version=f"aidycexplorer {__version__}")
    parser.add_argument(
        "locations",
        nargs="*",
        help="Carpetas o archivos a abrir. También acepta file:// y trash://",
    )
    args = parser.parse_args(argv)
    try:
        from .ui import run
    except ImportError as exc:
        print(f"No se puede abrir AidyCExplorer: {exc}", file=sys.stderr)
        return 1
    return run(args.locations)
