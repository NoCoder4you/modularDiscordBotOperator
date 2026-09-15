"""Minimal atomic process metadata used for conservative restart reconciliation."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .models import ProcessRecord, ProcessState


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    def save(self, records: list[ProcessRecord]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = {"version": 1, "processes": [self._encode(record) for record in records]}
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self) -> list[ProcessRecord]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") != 1 or not isinstance(raw.get("processes"), list):
                return []
            return [self._decode(item) for item in raw["processes"]]
        except (OSError, ValueError, TypeError, KeyError):
            return []

    @staticmethod
    def _encode(record: ProcessRecord) -> dict[str, object]:
        return {
            "bot_id": record.bot_id,
            "process_instance_id": record.process_instance_id,
            "pid": record.pid,
            "started_at": record.started_at.isoformat(),
            "os_start_ticks": record.os_start_ticks,
            "expected_argv": list(record.expected_argv),
            "state": record.state.value,
        }

    @staticmethod
    def _decode(raw: dict[str, object]) -> ProcessRecord:
        return ProcessRecord(
            bot_id=str(raw["bot_id"]),
            process_instance_id=str(raw["process_instance_id"]),
            pid=int(raw["pid"]),
            started_at=datetime.fromisoformat(str(raw["started_at"])),
            os_start_ticks=int(raw["os_start_ticks"]),
            expected_argv=tuple(str(value) for value in raw["expected_argv"]),
            state=ProcessState(str(raw["state"])),
            adopted=True,
        )
