"""Trusted runtime paths with enforced per-bot isolation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .exceptions import PathSecurityError
from .identifiers import validate_bot_id


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path

    def bot_data(self, bot_id: str, *parts: str) -> Path:
        """Resolve a path below exactly one bot's private data root."""
        bot_root = (self.root.resolve() / "data" / validate_bot_id(bot_id)).resolve()
        candidate = bot_root.joinpath(*parts).resolve()
        if not candidate.is_relative_to(bot_root):
            raise PathSecurityError("path escaped the bot data root")
        return candidate

    def bot_logs(self, bot_id: str) -> Path:
        return (self.root.resolve() / "logs" / validate_bot_id(bot_id)).resolve()
