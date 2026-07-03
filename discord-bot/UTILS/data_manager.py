"""Asynchronous-safe JSON data helpers scoped by Discord guild ID."""
from __future__ import annotations

import asyncio
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from UTILS.logger import get_logger

logger = get_logger(__name__)
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "DATA"
GUILDS_DIR = DATA_DIR / "guilds"
_LOCKS: dict[Path, asyncio.Lock] = {}
_LOCKS_GUARD = asyncio.Lock()


def _copy_default(default: Any) -> Any:
    """Return an independent copy of default data for safe reuse."""
    return copy.deepcopy(default)


def _validate_guild_id(guild_id: int | str) -> int:
    try:
        parsed = int(guild_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("guild_id must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError("guild_id must be a positive integer.")
    return parsed


def _validate_filename(filename: str) -> str:
    path = Path(filename)
    if path.name != filename or path.is_absolute() or ".." in path.parts:
        raise ValueError("filename must be a simple JSON filename, not a path.")
    if not path.suffix:
        filename = f"{filename}.json"
        path = Path(filename)
    if path.suffix != ".json" or path.stem in {"", "."}:
        raise ValueError("filename must be a .json file.")
    return filename


def _ensure_inside_data(path: Path) -> Path:
    resolved = path.resolve()
    data_root = DATA_DIR.resolve()
    if not resolved.is_relative_to(data_root):
        raise ValueError("resolved path escaped the DATA directory.")
    return resolved


async def _get_lock(path: Path) -> asyncio.Lock:
    async with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, asyncio.Lock())


def get_guild_directory(guild_id: int | str) -> Path:
    """Return the validated DATA/guilds/<guild_id> directory path."""
    parsed = _validate_guild_id(guild_id)
    return _ensure_inside_data(GUILDS_DIR / str(parsed))


def _default_settings(guild_id: int) -> dict[str, Any]:
    return {
        "guild_id": guild_id,
        "prefix": "!",
        "enabled_cogs": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def ensure_guild_data(guild_id: int | str) -> Path:
    """Create a guild data directory and default settings without overwriting data."""
    parsed = _validate_guild_id(guild_id)
    guild_dir = get_guild_directory(parsed)
    guild_dir.mkdir(parents=True, exist_ok=True)
    await load_guild_json(parsed, "settings", _default_settings(parsed))
    return guild_dir


async def load_guild_json(guild_id: int | str, filename: str, default: Any) -> Any:
    """Load a guild JSON file, creating it from default data when missing."""
    await ensure_data_root()
    guild_dir = get_guild_directory(guild_id)
    guild_dir.mkdir(parents=True, exist_ok=True)
    file_path = _ensure_inside_data(guild_dir / _validate_filename(filename))
    lock = await _get_lock(file_path)
    async with lock:
        if not file_path.exists():
            data = _copy_default(default)
            await _atomic_write_json(file_path, data)
            return data
        try:
            with file_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            logger.error("Malformed JSON in %s: %s", file_path, exc)
            raise ValueError(f"Malformed JSON in {file_path.name} for guild {guild_id}.") from exc


async def save_guild_json(guild_id: int | str, filename: str, data: Any) -> None:
    """Atomically save JSON data for one guild-specific file."""
    await ensure_data_root()
    guild_dir = get_guild_directory(guild_id)
    guild_dir.mkdir(parents=True, exist_ok=True)
    file_path = _ensure_inside_data(guild_dir / _validate_filename(filename))
    lock = await _get_lock(file_path)
    async with lock:
        await _atomic_write_json(file_path, data)


async def delete_guild_json(guild_id: int | str, filename: str) -> bool:
    """Delete one guild JSON file and return True when a file was removed."""
    file_path = _ensure_inside_data(get_guild_directory(guild_id) / _validate_filename(filename))
    lock = await _get_lock(file_path)
    async with lock:
        if not file_path.exists():
            return False
        file_path.unlink()
        return True


async def ensure_data_root() -> None:
    """Create the DATA and DATA/guilds directories if they do not exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GUILDS_DIR.mkdir(parents=True, exist_ok=True)


async def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON through a temporary file and atomic replace."""
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=4)
        handle.write("\n")
    os.replace(temp_path, path)
