"""CDA Pay paths rooted in the platform's per-bot data boundary."""

from __future__ import annotations

from pathlib import Path

from cda_pay.config import CDAPayConfig

BOT_ID = "cda-pay"


def data_path(*parts: str) -> Path:
    """Resolve a path securely below runtime/data/cda-pay."""
    return CDAPayConfig.from_env(require_token=False).paths.bot_data(BOT_ID, *parts).path


JSON_DIR = data_path("JSON")
BACKUP_DIR = data_path("BACKUPS")
JSON_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
SERVER_CONFIG_PATH = JSON_DIR / "server.json"
VOID_DATA_FILE = JSON_DIR / "CDAVoidData.json"
