"""RPA Admin compatibility paths backed by the platform's isolated runtime root."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from shared.bot_core import RuntimePaths
from shared.bot_core.exceptions import PathSecurityError

BOT_ID = "rpa-admin"
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT
DEFAULTS_DIR = PACKAGE_ROOT.parents[1] / "defaults"


def _runtime_paths() -> RuntimePaths:
    return RuntimePaths(Path(os.environ.get("MDBO_RUNTIME_ROOT", "./runtime")).expanduser())


def json_dir() -> Path:
    """Return this bot's data directory, never another bot's runtime directory."""
    return _runtime_paths().bot_data(BOT_ID).path


def cogs_dir() -> Path:
    return PACKAGE_ROOT / "cogs"


def _safe_filename(filename: str) -> str:
    candidate = Path(filename)
    if candidate.name != filename or filename in {"", ".", ".."}:
        raise PathSecurityError("RPA Admin data filenames must be a single path component")
    return filename


def json_file(filename: str) -> Path:
    """Resolve a state/config file and seed a sanitized application default once."""
    safe_name = _safe_filename(filename)
    target = _runtime_paths().bot_data(BOT_ID, safe_name).path
    default = DEFAULTS_DIR / safe_name
    if not target.exists() and default.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(default, target)
    return target


def cogs_file(filename: str) -> Path:
    return cogs_dir() / _safe_filename(filename)
