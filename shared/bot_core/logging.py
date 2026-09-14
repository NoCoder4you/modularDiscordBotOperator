"""Supervisor-friendly structured console logging."""

from __future__ import annotations
import logging
import sys
import time

from .identifiers import validate_bot_id

_FORMAT = "%(asctime)sZ | %(levelname)s | bot=%(bot_id)s | %(name)s | %(message)s"


class _BotId(logging.Filter):
    def __init__(self, bot_id: str):
        super().__init__()
        self.bot_id = bot_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.bot_id = self.bot_id
        return True


def configure_logging(bot_id: str, level: str = "INFO") -> logging.Logger:
    """Configure one named bot logger idempotently; never logs configuration values."""
    validate_bot_id(bot_id)
    logger = logging.getLogger(f"bot.{bot_id}")
    logger.setLevel(level)
    logger.propagate = False
    if not any(getattr(handler, "_bot_core", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler._bot_core = True  # type: ignore[attr-defined]
        handler.addFilter(_BotId(bot_id))
        formatter = logging.Formatter(_FORMAT, "%Y-%m-%dT%H:%M:%S")
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger
