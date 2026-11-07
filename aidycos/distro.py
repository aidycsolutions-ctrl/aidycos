"""Linux distribution detection based on the standard os-release file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Distribution:
    id: str
    version_id: str
    id_like: tuple[str, ...] = ()
    pretty_name: str = "Linux"

    @property
    def family(self) -> str | None:
        identifiers = (self.id, *self.id_like)
        if any(name in {"debian", "ubuntu", "linuxmint", "pop"} for name in identifiers):
            return "debian"
        if any(name in {"arch", "manjaro", "cachyos"} for name in identifiers):
            return "arch"
        if any(name in {"fedora", "rhel", "centos"} for name in identifiers):
            return "fedora"
        return None


def parse_os_release(content: str) -> dict[str, str]:
    """Parse the simple KEY=VALUE format used by /etc/os-release."""
    values: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def detect_distribution(path: str | Path = "/etc/os-release") -> Distribution:
    values = parse_os_release(Path(path).read_text(encoding="utf-8"))
    return Distribution(
        id=values.get("ID", "").lower(),
        version_id=values.get("VERSION_ID", ""),
        id_like=tuple(values.get("ID_LIKE", "").lower().split()),
        pretty_name=values.get("PRETTY_NAME", values.get("NAME", "Linux")),
    )
