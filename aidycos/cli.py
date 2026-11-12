from __future__ import annotations

import argparse
import os
import subprocess
import sys

from . import __version__
from .distro import detect_distribution
from .modules import ModuleError, load_modules
from .plan import build_plan
from .adapters.factory import UnsupportedDistribution, adapter_for


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aidycos", description="Prepara Linux con módulos reproducibles")
    parser.add_argument("--version", action="version", version=f"AidyCOS {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("modules", help="Lista los módulos disponibles")
    commands.add_parser("doctor", help="Muestra distribución y soporte disponible")
    uninstall = commands.add_parser(
        "uninstall",
        help="Quita el perfil AidyCOS y restaura respaldos del sistema anterior",
    )
    uninstall.add_argument("--dry-run", action="store_true", help="Solo muestra qué haría")
    uninstall.add_argument("--yes", "-y", action="store_true", help="No pedir confirmación")
    uninstall.add_argument("--no-reboot", action="store_true", help="No reiniciar al terminar")
    uninstall.add_argument(
        "--remove-packages",
        action="store_true",
        help="También quita paquetes Hyprland/SDDM del perfil",
    )
    for command, help_text in (("plan", "Muestra qué instalaría un módulo"),
                               ("install", "Planifica o instala un módulo")):
        sub = commands.add_parser(command, help=help_text)
        sub.add_argument("modules", nargs="+", help="Módulos a incluir")
        if command == "install":
            sub.add_argument("--apply", action="store_true", help="Ejecuta los comandos del gestor de paquetes")
    return parser


def _uninstall_script() -> str:
    candidates = [
        os.environ.get("AIDYCOS_UNINSTALL"),
        os.path.expanduser("~/.local/bin/aidycos-uninstall"),
        "/usr/local/bin/aidycos-uninstall",
        os.path.join(os.path.dirname(__file__), "..", "scripts", "uninstall-debian-profile.sh"),
    ]
    for path in candidates:
        if not path:
            continue
        resolved = os.path.abspath(path)
        if os.path.isfile(resolved) and os.access(resolved, os.X_OK):
            return resolved
        if os.path.isfile(resolved):
            return resolved
    raise FileNotFoundError(
        "No se encontró aidycos-uninstall. Reaplica el perfil o usa "
        "scripts/uninstall-debian-profile.sh"
    )


def _run_uninstall(args: argparse.Namespace) -> int:
    script = _uninstall_script()
    argv = ["bash", script]
    if args.dry_run:
        argv.append("--dry-run")
    if args.yes:
        argv.append("--yes")
    if args.no_reboot:
        argv.append("--no-reboot")
    if args.remove_packages:
        argv.append("--remove-packages")
    return subprocess.run(argv, check=False).returncode


def _print_doctor() -> int:
    try:
        distro = detect_distribution()
    except OSError as error:
        print(f"No se pudo leer /etc/os-release: {error}", file=sys.stderr)
        return 2
    print(f"Distribución: {distro.pretty_name} (ID={distro.id}, VERSION_ID={distro.version_id or 'desconocida'})")
    print(f"Familia detectada: {distro.family or 'desconocida'}")
    try:
        adapter = adapter_for(distro)
    except UnsupportedDistribution as error:
        print(f"Estado: {error}")
        return 1
    print(f"Estado: soportada mediante {adapter.name}")
    return 0


def _show_plan(names: list[str], *, apply: bool) -> int:
    modules = load_modules()
    distro = detect_distribution()
    adapter = adapter_for(distro)
    plan = build_plan(names, modules, distro, adapter.name)
    print(f"Sistema: {distro.pretty_name}")
    print("Módulos: " + ", ".join(module.name for module in plan.modules))
    print("Paquetes: " + (" ".join(plan.packages) if plan.packages else "ninguno"))
    if not apply:
        print("Modo: solo planificación (sin cambios en el sistema). Usa --apply para instalar.")
        return 0
    if not plan.packages:
        print("No hay paquetes para instalar.")
        return 0
    runner = lambda argv, check=False: subprocess.run(  # noqa: E731
        argv, check=check, env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    ).returncode
    try:
        return adapter.install(plan.packages, is_root=(os.geteuid() == 0), runner=runner)
    except FileNotFoundError as error:
        print(f"No se encontró un comando requerido: {error.filename}", file=sys.stderr)
        return 127


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "modules":
            for module in load_modules().values():
                print(f"{module.name}\t{module.description}")
            return 0
        if args.command == "doctor":
            return _print_doctor()
        if args.command == "uninstall":
            return _run_uninstall(args)
        return _show_plan(args.modules, apply=getattr(args, "apply", False))
    except (ModuleError, UnsupportedDistribution, OSError, FileNotFoundError) as error:
        print(f"AidyCOS: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
