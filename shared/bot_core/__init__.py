"""Small, bot-agnostic public API for managed Discord bot infrastructure."""

from .config import PlatformConfig
from .exceptions import BotCoreError, PathSecurityError, ValidationError
from .identifiers import validate_bot_id
from .manifest import BotManifest, StartupPolicy, load_manifest
from .paths import RuntimePaths
from .secure_path import AuthorizedPath
from .state import BotState, BotStatus

__all__ = [
    "AuthorizedPath",
    "BotCoreError",
    "BotManifest",
    "BotState",
    "BotStatus",
    "PathSecurityError",
    "PlatformConfig",
    "RuntimePaths",
    "StartupPolicy",
    "ValidationError",
    "load_manifest",
    "validate_bot_id",
]
