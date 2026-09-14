"""Trusted runtime paths with enforced per-bot isolation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .exceptions import PathSecurityError
from .identifiers import validate_bot_id
from .secure_path import AuthorizedPath


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path

    def _trusted_directory(self, kind: str, bot_id: str) -> Path:
        """Resolve a bot directory while retaining the runtime root as trust boundary."""
        runtime_root = self.root.resolve()
        category_root = (runtime_root / kind).resolve()
        if not category_root.is_relative_to(runtime_root):
            raise PathSecurityError(f"{kind} root escaped the runtime root")

        bot_root = (category_root / validate_bot_id(bot_id)).resolve()
        if not bot_root.is_relative_to(category_root):
            raise PathSecurityError(f"bot {kind} root escaped the {kind} root")
        return bot_root

    def bot_data(self, bot_id: str, *parts: str) -> AuthorizedPath:
        """Return an authorized path that secure writers open without following symlinks."""
        runtime_root = self.root.resolve()
        bot_root = self._trusted_directory("data", bot_id)
        candidate = bot_root.joinpath(*parts).resolve()
        if not candidate.is_relative_to(bot_root):
            raise PathSecurityError("path escaped the bot data root")
        return AuthorizedPath(runtime_root, candidate.relative_to(runtime_root).parts)

    def bot_logs(self, bot_id: str) -> Path:
        return self._trusted_directory("logs", bot_id)
