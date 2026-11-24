"""aidycalc CLI."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation

from . import __version__
from .engine import CalcError, evaluate, format_number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aidycalc",
        description="Calculadora de AidyCOS",
    )
    parser.add_argument("--version", action="version", version=f"aidycalc {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("ui", help="Abrir la ventana")
    evaluate_parser = sub.add_parser("eval", help="Calcular una expresión")
    evaluate_parser.add_argument("expression", nargs="+", help="Expresión, por ejemplo 200+10%%")
    evaluate_parser.add_argument("--angle", choices=("deg", "rad"), default="deg")
    evaluate_parser.add_argument("--ans", default=None, help="Valor de ans")

    args = parser.parse_args(argv)
    if args.cmd == "eval":
        try:
            ans = None if args.ans is None else Decimal(str(args.ans).replace(",", "."))
        except InvalidOperation:
            print("ans no es un número", flush=True)
            return 1
        try:
            value = evaluate(" ".join(args.expression), angle=args.angle, ans=ans)
        except CalcError as exc:
            print(str(exc), flush=True)
            return 1
        print(format_number(value), flush=True)
        return 0

    from .ui import run

    return run()
