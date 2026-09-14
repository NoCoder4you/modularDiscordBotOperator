"""Compatibility path adapter backed by Stage 1 per-bot runtime isolation."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from shared.bot_core import RuntimePaths
from shared.bot_core.jsonio import atomic_write_json

BOT_ID = "cda-admin"
_DEFAULTS = Path(__file__).resolve().parents[1] / "defaults"


def data_path(filename: str) -> Path:
    """Resolve a legacy JSON filename under this bot's trusted runtime directory."""
    path = Path(filename)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("CDA Admin data paths must be relative and may not traverse parents")
    parts = path.parts[1:] if path.parts and path.parts[0] == "JSON" else path.parts
    root = Path(os.environ.get("MDBO_RUNTIME_ROOT", "./runtime")).expanduser()
    destination = RuntimePaths(root).bot_data(BOT_ID, *parts).path
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        default = _DEFAULTS.joinpath(*parts)
        value: Any = json.loads(default.read_text(encoding="utf-8")) if default.exists() else {}
        atomic_write_json(RuntimePaths(root).bot_data(BOT_ID, *parts), value)
    return destination
