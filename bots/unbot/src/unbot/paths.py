"""UNBOT paths backed by the platform's isolated runtime capability."""

from pathlib import Path

from shared.bot_core.config import PlatformConfig
from shared.bot_core.paths import RuntimePaths

BOT_ID = "unbot"


def data_root() -> Path:
    """Return the resolved, traversal-protected UNBOT data directory."""
    return RuntimePaths(PlatformConfig.from_env().runtime_root).bot_data(BOT_ID).path
