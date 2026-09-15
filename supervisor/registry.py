"""Deny-by-default catalog backed by manifests below one trusted repository root."""

from __future__ import annotations

from pathlib import Path

from shared.bot_core.exceptions import ValidationError
from shared.bot_core.identifiers import validate_bot_id
from shared.bot_core.manifest import load_manifest

from .errors import UnknownBotError
from .models import RegisteredBot


class BotRegistry:
    def __init__(self, repository_root: Path, runtime_root: Path) -> None:
        self.repository_root = repository_root.resolve(strict=True)
        self.runtime_root = runtime_root.resolve()
        self._bots = self._load()

    def _contained(self, candidate: Path, root: Path, label: str) -> Path:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise ValidationError(f"{label} escapes its trusted root")
        return resolved

    def _load(self) -> dict[str, RegisteredBot]:
        bots_root = self._contained(self.repository_root / "bots", self.repository_root, "bots root")
        manifests = sorted(bots_root.glob("*/bot.toml"))
        result: dict[str, RegisteredBot] = {}
        for path in manifests:
            manifest = load_manifest(path)
            if manifest.bot_id in result:
                raise ValidationError(f"duplicate bot ID: {manifest.bot_id}")
            working = self._contained(
                self.repository_root / manifest.working_directory,
                self.repository_root,
                "working directory",
            )
            executable = self._contained(
                self.repository_root / manifest.python_executable,
                self.repository_root,
                "python executable",
            )
            runtime = self._contained(self.runtime_root / manifest.bot_id, self.runtime_root, "runtime")
            result[manifest.bot_id] = RegisteredBot(
                manifest.bot_id,
                manifest.display_name,
                manifest.enabled,
                manifest.startup_policy.value,
                manifest.entry_point,
                executable,
                working,
                runtime,
                manifest.bot_id.upper().replace("-", "_") + "_TOKEN",
                manifest.shutdown_timeout_seconds,
            )
        return result

    def get(self, bot_id: str) -> RegisteredBot:
        try:
            validate_bot_id(bot_id)
        except ValidationError as exc:
            raise UnknownBotError("unknown bot") from exc
        try:
            return self._bots[bot_id]
        except KeyError as exc:
            raise UnknownBotError("unknown bot") from exc

    def list(self) -> tuple[RegisteredBot, ...]:
        return tuple(self._bots[key] for key in sorted(self._bots))
