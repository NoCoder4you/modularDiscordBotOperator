"""Immutable platform configuration loaded without global mutation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class PlatformConfig:
    runtime_root: Path
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "PlatformConfig":
        values = os.environ if env is None else env
        root = values.get("MDBO_RUNTIME_ROOT", "./runtime").strip()
        if not root:
            raise ValidationError("MDBO_RUNTIME_ROOT cannot be empty")
        level = values.get("MDBO_LOG_LEVEL", "INFO").upper().strip()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValidationError("MDBO_LOG_LEVEL is invalid")
        return cls(Path(root).expanduser(), level)
