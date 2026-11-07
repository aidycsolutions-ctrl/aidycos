"""Load and validate module manifests shipped with AidyCOS."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib


MODULES_DIR = Path(__file__).resolve().parent / "modules"
MODULE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._:-]*$")


class ModuleError(ValueError):
    """A module manifest is invalid or cannot be loaded."""


@dataclass(frozen=True)
class Module:
    name: str
    description: str
    packages: dict[str, tuple[str, ...]]
    dependencies: tuple[str, ...] = ()


def load_module(path: str | Path) -> Module:
    path = Path(path)
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    name = raw.get("name", path.parent.name)
    if not isinstance(name, str) or not MODULE_NAME.fullmatch(name):
        raise ModuleError(f"Nombre de módulo inválido: {name!r}")
    package_map = raw.get("packages", {})
    if not isinstance(package_map, dict):
        raise ModuleError(f"El campo packages de {name} debe ser una tabla")
    packages: dict[str, tuple[str, ...]] = {}
    for adapter, names in package_map.items():
        if not isinstance(adapter, str) or not isinstance(names, list):
            raise ModuleError(f"Lista de paquetes inválida para {name}/{adapter}")
        if not all(isinstance(item, str) and PACKAGE_NAME.fullmatch(item) for item in names):
            raise ModuleError(f"Nombre de paquete inválido en el módulo {name}")
        packages[adapter] = tuple(names)
    dependencies = raw.get("depends_on", [])
    if not isinstance(dependencies, list) or not all(isinstance(x, str) for x in dependencies):
        raise ModuleError(f"depends_on debe ser una lista de nombres en {name}")
    return Module(name, str(raw.get("description", "")), packages, tuple(dependencies))


def load_modules(directory: str | Path = MODULES_DIR) -> dict[str, Module]:
    modules: dict[str, Module] = {}
    for manifest in sorted(Path(directory).glob("*/module.toml")):
        module = load_module(manifest)
        if module.name in modules:
            raise ModuleError(f"Módulo duplicado: {module.name}")
        modules[module.name] = module
    return modules


def resolve_modules(names: list[str], modules: dict[str, Module]) -> list[Module]:
    """Resolve dependencies in order and reject cycles or unknown modules."""
    ordered: list[Module] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name not in modules:
            raise ModuleError(f"Módulo desconocido: {name}")
        if name in visiting:
            raise ModuleError(f"Dependencia circular detectada en: {name}")
        if name in visited:
            return
        visiting.add(name)
        module = modules[name]
        for dependency in module.dependencies:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
        ordered.append(module)

    for name in names:
        visit(name)
    return ordered
