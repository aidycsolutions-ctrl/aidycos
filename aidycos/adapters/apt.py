from __future__ import annotations

from .base import PackageAdapter


class AptAdapter(PackageAdapter):
    name = "apt"

    @staticmethod
    def _privileged(argv: list[str], *, is_root: bool) -> list[str]:
        return argv if is_root else ["sudo", *argv]

    def update_command(self, *, is_root: bool) -> list[str]:
        return self._privileged(["apt-get", "update"], is_root=is_root)

    def install_command(self, packages: tuple[str, ...], *, is_root: bool) -> list[str]:
        return self._privileged(
            ["apt-get", "install", "--no-install-recommends", "-y", *packages],
            is_root=is_root,
        )
