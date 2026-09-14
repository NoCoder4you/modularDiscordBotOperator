"""Stable managed-bot identifiers."""

from __future__ import annotations

import re

from .exceptions import ValidationError

_BOT_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def validate_bot_id(value: str) -> str:
    """Return a canonical bot ID or reject unsafe/ambiguous input."""
    if not isinstance(value, str) or not _BOT_ID.fullmatch(value):
        raise ValidationError("bot ID must be lowercase kebab-case")
    return value
