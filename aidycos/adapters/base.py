from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


Runner = Callable[..., int]


class PackageAdapter(ABC):
    name: str

    @abstractmethod
    def install_command(self, packages: tuple[str, ...], *, is_root: bool) -> list[str]:
        """Return an argv command. Implementations must not invoke a shell."""

    @abstractmethod
    def update_command(self, *, is_root: bool) -> list[str]:
        """Return an argv command to refresh package metadata."""

    def install(self, packages: tuple[str, ...], *, is_root: bool, runner: Runner) -> int:
        if not packages:
            return 0
        result = runner(self.update_command(is_root=is_root), check=False)
        if result:
            return result
        return runner(self.install_command(packages, is_root=is_root), check=False)
