"""Typed lifecycle and process records. These models never contain secrets."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProcessState(StrEnum):
    DISABLED = "disabled"
    OFFLINE = "offline"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    RESTARTING = "restarting"
    CRASHED = "crashed"
    UNKNOWN = "unknown"


class LifecycleAction(StrEnum):
    START = "start"
    STOP = "stop"
    RESTART = "restart"


class OperationStatus(StrEnum):
    REQUESTED = "requested"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RegisteredBot:
    bot_id: str
    display_name: str
    enabled: bool
    startup_policy: str
    entry_point: str
    executable: Path
    working_directory: Path
    runtime_directory: Path
    token_environment_variable: str
    shutdown_timeout_seconds: float


@dataclass(slots=True)
class ProcessRecord:
    bot_id: str
    process_instance_id: str
    pid: int
    started_at: datetime
    os_start_ticks: int
    expected_argv: tuple[str, ...]
    state: ProcessState
    adopted: bool = False
    exit_code: int | None = None
    exited_at: datetime | None = None
    expected_exit: bool = False
    forced: bool = False


@dataclass(slots=True)
class OperationRecord:
    operation_id: str
    bot_id: str
    action: LifecycleAction
    requested_at: datetime
    status: OperationStatus = OperationStatus.REQUESTED
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_category: str | None = None
    actor: str | None = None


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    operation: OperationRecord
    previous_state: ProcessState
    current_state: ProcessState
    process_instance_id: str | None


@dataclass(frozen=True, slots=True)
class OutputLine:
    sequence: int
    received_at: datetime
    bot_id: str
    process_instance_id: str
    stream: str
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    name: str
    timestamp: datetime
    bot_id: str
    operation_id: str | None
    process_instance_id: str | None
    actor: str | None = None
    error_category: str | None = None
