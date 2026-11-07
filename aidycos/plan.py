from __future__ import annotations

from dataclasses import dataclass

from .distro import Distribution
from .modules import Module, resolve_modules


@dataclass(frozen=True)
class InstallPlan:
    distribution: Distribution
    modules: tuple[Module, ...]
    adapter_name: str
    packages: tuple[str, ...]


def build_plan(names: list[str], modules: dict[str, Module], distribution: Distribution,
               adapter_name: str) -> InstallPlan:
    selected = resolve_modules(names, modules)
    packages: list[str] = []
    for module in selected:
        for package in module.packages.get(adapter_name, ()):
            if package not in packages:
                packages.append(package)
    return InstallPlan(distribution, tuple(selected), adapter_name, tuple(packages))
