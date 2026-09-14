"""Authorized path capability retaining its trusted-root relationship."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .exceptions import PathSecurityError


@dataclass(frozen=True, slots=True)
class AuthorizedPath:
    """A path whose relative components must be opened below ``trusted_root``."""

    trusted_root: Path
    relative_parts: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.trusted_root != self.trusted_root.resolve():
            raise PathSecurityError("trusted root must be resolved")
        if any(
            not component or component in {".", ".."} or Path(component).name != component
            for component in self.relative_parts
        ):
            raise PathSecurityError("authorized path contains an invalid component")

    @property
    def path(self) -> Path:
        return self.trusted_root.joinpath(*self.relative_parts)

    def __fspath__(self) -> str:
        return str(self.path)

    def is_relative_to(self, other: Path) -> bool:
        return self.path.is_relative_to(other)
