"""Logging helpers for the Discord bot."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[1] / "LOGS"
LOG_FILE = LOG_DIR / "bot.log"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure console and rotating-file logging without duplicate handlers."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    if not any(getattr(handler, "_bot_console", False) for handler in root_logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        console_handler._bot_console = True  # type: ignore[attr-defined]
        root_logger.addHandler(console_handler)

    if not any(getattr(handler, "_bot_file", False) for handler in root_logger.handlers):
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        file_handler._bot_file = True  # type: ignore[attr-defined]
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, configuring logging first if needed."""
    setup_logging()
    return logging.getLogger(name)
