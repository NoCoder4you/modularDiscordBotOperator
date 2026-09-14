"""Exceptions exposed by the intentionally small bot-core API."""


class BotCoreError(Exception):
    """Base error for shared platform infrastructure."""


class ValidationError(BotCoreError, ValueError):
    """Configuration or manifest input failed validation."""


class PathSecurityError(BotCoreError, ValueError):
    """A requested path was outside its trusted root."""
