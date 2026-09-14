"""CDA Admin configuration, loaded explicitly from the process environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from shared.bot_core import PlatformConfig, RuntimePaths, ValidationError


@dataclass(frozen=True, slots=True)
class CDAAdminConfig:
    token: str
    runtime_root: Path
    log_level: str

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, *, require_token: bool = True
    ) -> "CDAAdminConfig":
        values = os.environ if env is None else env
        platform = PlatformConfig.from_env(values)
        token = values.get("CDA_ADMIN_TOKEN", "").strip()
        if require_token and not token:
            raise ValidationError("CDA_ADMIN_TOKEN is required")
        return cls(token=token, runtime_root=platform.runtime_root, log_level=platform.log_level)

    @property
    def paths(self) -> RuntimePaths:
        return RuntimePaths(self.runtime_root)

