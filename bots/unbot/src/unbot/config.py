"""Environment-backed UNBOT configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from shared.bot_core.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class UnbotConfig:
    token: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "UnbotConfig":
        values = os.environ if env is None else env
        token = values.get("UNBOT_TOKEN", "").strip()
        if not token:
            raise ValidationError("UNBOT_TOKEN is required")
        return cls(token=token)
