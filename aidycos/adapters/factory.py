from __future__ import annotations

from ..distro import Distribution
from .apt import AptAdapter
from .base import PackageAdapter


class UnsupportedDistribution(RuntimeError):
    pass


def adapter_for(distribution: Distribution) -> PackageAdapter:
    # Debian is the only enabled target in 0.1.0. Family detection is already
    # available so later adapters can be added without changing the CLI.
    if distribution.id == "debian" and distribution.version_id.split(".")[0] == "13":
        return AptAdapter()
    raise UnsupportedDistribution(
        f"Todavía no hay adaptador instalable para {distribution.pretty_name}. "
        "La primera versión soporta Debian 13; Arch, Ubuntu y Fedora están previstos."
    )
