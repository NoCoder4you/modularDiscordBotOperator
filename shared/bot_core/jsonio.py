"""Atomic JSON persistence for already-authorized paths."""

from __future__ import annotations
import json
import os
import tempfile
import secrets
from pathlib import Path
from typing import Any

from .exceptions import PathSecurityError
from .secure_path import AuthorizedPath


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


def _atomic_write_authorized(path: AuthorizedPath, value: Any) -> None:
    """Write relative to held directory descriptors without following symlinks."""
    if os.name != "posix":
        atomic_write_json(path.path, value)
        return
    if not path.relative_parts:
        raise PathSecurityError("authorized JSON path has no filename")

    _create_parent_directories(path.trusted_root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.trusted_root, flags)
    temporary = f".{path.relative_parts[-1]}.{secrets.token_hex(8)}.tmp"
    try:
        for component in path.relative_parts[:-1]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
                os.fsync(descriptor)
            except FileExistsError:
                pass
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except OSError as exc:
                raise PathSecurityError("authorized path contains an unsafe component") from exc
            os.close(descriptor)
            descriptor = child

        file_descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=descriptor
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            file_descriptor = -1
            os.rename(
                temporary,
                path.relative_parts[-1],
                src_dir_fd=descriptor,
                dst_dir_fd=descriptor,
            )
            os.fsync(descriptor)
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except FileNotFoundError:
                pass
    finally:
        os.close(descriptor)


def atomic_write_json(path: Path | AuthorizedPath, value: Any) -> None:
    if isinstance(path, AuthorizedPath):
        _atomic_write_authorized(path, value)
        return
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
