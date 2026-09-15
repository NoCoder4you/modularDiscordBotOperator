"""Strict TOML manifest model for independently managed bots."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .exceptions import ValidationError
from .identifiers import validate_bot_id


class StartupPolicy(StrEnum):
    MANUAL = "manual"
    ALWAYS = "always"
    ON_FAILURE = "on-failure"


@dataclass(frozen=True, slots=True)
class BotManifest:
    bot_id: str
    display_name: str
    entry_point: str
    working_directory: str = "."
    enabled: bool = False
    startup_policy: StartupPolicy = StartupPolicy.MANUAL
    management_agent: bool = False
    colour: str | None = None
    icon: str | None = None
    python_executable: str = ".venv/bin/python"
    shutdown_timeout_seconds: float = 15.0

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "BotManifest":
        allowed = {
            "id",
            "display_name",
            "entry_point",
            "working_directory",
            "enabled",
            "startup_policy",
            "management_agent",
            "colour",
            "icon",
            "python_executable",
            "shutdown_timeout_seconds",
        }
        unknown = raw.keys() - allowed
        if unknown:
            raise ValidationError(f"unknown manifest fields: {', '.join(sorted(unknown))}")
        required = ("id", "display_name", "entry_point")
        if any(not isinstance(raw.get(key), str) or not raw[key].strip() for key in required):
            raise ValidationError("id, display_name and entry_point must be non-empty strings")
        bot_id = validate_bot_id(raw["id"])
        entry_point = raw["entry_point"]
        if not _valid_entry_point(entry_point):
            raise ValidationError("entry_point must be a Python module or module:callable")
        working = raw.get("working_directory", ".")
        if (
            not isinstance(working, str)
            or Path(working).is_absolute()
            or ".." in Path(working).parts
        ):
            raise ValidationError("working_directory must be a relative path without '..'")
        for field in ("enabled", "management_agent"):
            if field in raw and not isinstance(raw[field], bool):
                raise ValidationError(f"{field} must be a boolean")
        try:
            policy = StartupPolicy(raw.get("startup_policy", "manual"))
        except ValueError as exc:
            raise ValidationError("invalid startup_policy") from exc
        colour = raw.get("colour")
        if colour is not None and (not isinstance(colour, str) or not re_full_colour(colour)):
            raise ValidationError("colour must use #RRGGBB format")
        icon = raw.get("icon")
        if icon is not None and not isinstance(icon, str):
            raise ValidationError("icon must be a string")
        executable = raw.get("python_executable", ".venv/bin/python")
        executable_path = Path(executable) if isinstance(executable, str) else Path("/")
        if (
            not isinstance(executable, str)
            or not executable
            or executable_path.is_absolute()
            or ".." in executable_path.parts
        ):
            raise ValidationError("python_executable must be a repository-relative path")
        timeout = raw.get("shutdown_timeout_seconds", 15.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 300:
            raise ValidationError("shutdown_timeout_seconds must be between 0 and 300")
        return cls(
            bot_id,
            raw["display_name"].strip(),
            entry_point,
            working,
            raw.get("enabled", False),
            policy,
            raw.get("management_agent", False),
            colour,
            icon,
            executable,
            float(timeout),
        )


def _valid_entry_point(value: str) -> bool:
    pieces = value.split(":")
    return len(pieces) <= 2 and all(
        piece and all(part.isidentifier() for part in piece.split(".")) for piece in pieces
    )


def re_full_colour(value: str) -> bool:
    return (
        len(value) == 7
        and value[0] == "#"
        and all(char in "0123456789abcdefABCDEF" for char in value[1:])
    )


def load_manifest(path: Path) -> BotManifest:
    """Load a UTF-8 TOML manifest; secrets are explicitly forbidden."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValidationError(f"could not load manifest {path}") from exc
    if set(raw) != {"bot"} or not isinstance(raw["bot"], dict):
        raise ValidationError("manifest must contain only one [bot] table")
    forbidden = {key for key in raw["bot"] if "token" in key.lower() or "secret" in key.lower()}
    if forbidden:
        raise ValidationError("secrets are forbidden in bot manifests")
    manifest = BotManifest.from_mapping(raw["bot"])
    if path.parent.name != manifest.bot_id:
        raise ValidationError("manifest ID must match its directory name")
    return manifest
