"""Atomic JSON persistence for already-authorized paths."""

from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _fsync_directory(path: Path) -> None:
    """Persist directory-entry changes on POSIX filesystems."""
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _create_parent_directories(path: Path) -> None:
    """Create and persist a missing parent hierarchy."""
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent

    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix" and missing:
        # Sync each new directory, then the existing ancestor whose entry now
        # references the highest newly created directory.
        for directory in missing:
            _fsync_directory(directory)
        _fsync_directory(current)


def atomic_write_json(path: Path, value: Any) -> None:
    _create_parent_directories(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
