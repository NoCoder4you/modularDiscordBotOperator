"""Environment configuration for the Discord bot."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class BotConfig:
    """Validated bot configuration loaded from environment variables."""

    discord_token: str
    test_guild_id: int | None = None
    owner_id: int | None = None
    command_prefix: str = "!"


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer when provided.") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be a positive integer when provided.")
    return parsed


def load_config() -> BotConfig:
    """Load and validate environment configuration from `.env` and the shell."""
    load_dotenv()

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "your_discord_bot_token":
        raise ConfigError("DISCORD_TOKEN is required. Add it to your .env file or environment.")

    return BotConfig(
        discord_token=token,
        test_guild_id=_optional_int("TEST_GUILD_ID"),
        owner_id=_optional_int("OWNER_ID"),
        command_prefix=os.getenv("COMMAND_PREFIX", "!").strip() or "!",
    )
