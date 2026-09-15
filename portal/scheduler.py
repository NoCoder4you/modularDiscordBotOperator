"""Closed, durable Stage 15 administrative scheduler.

Only declarative definitions from :data:`ADMINISTRATIVE_TASK_CATALOG` are persisted.
The scheduler deliberately contains no callable, command, path, URL, or import resolver.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Callable, Mapping, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .backups import TRUSTED_BACKUP_PLANS
from .bot_operations import TRUSTED_CAPABILITY_CATALOG
from .management import Principal

UTC = timezone.utc
CANONICAL_BOTS = frozenset({"cda-admin", "cda-pay", "unbot", "rpa-admin"})
ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SAFE_NAME = re.compile(r"^[\w .()-]{1,80}$", re.ASCII)
MIN_INTERVAL_SECONDS = 15 * 60
MAX_HORIZON = timedelta(days=3660)
SCHEMA_VERSION = 1


class SchedulerError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.safe_message, self.status = code, message, status


class ConcurrencyPolicy(StrEnum):
    FORBID_OVERLAP = "forbid_overlap"


class MisfirePolicy(StrEnum):
    SKIP = "skip"
    GRACE = "run_if_within_grace_window"


class ExecutionStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    MISFIRED = "misfired"
    AUTHORIZATION_REVOKED = "authorization_revoked"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AdministrativeTaskType:
    task_type_id: str
    display_name: str
    underlying_permission: str
    supported_bots: frozenset[str]
    parameter_names: frozenset[str] = frozenset()
    requires_ready: bool = False
    definition_version: int = 1
    concurrency: ConcurrencyPolicy = ConcurrencyPolicy.FORBID_OVERLAP
    misfire: MisfirePolicy = MisfirePolicy.GRACE
    grace_seconds: int = 900


ADMINISTRATIVE_TASK_CATALOG: Mapping[str, AdministrativeTaskType] = {
    "backup.create": AdministrativeTaskType(
        "backup.create",
        "Create trusted backup",
        "backups.create",
        frozenset(bot for bot, _ in TRUSTED_BACKUP_PLANS),
        frozenset({"plan_id"}),
    ),
    "bot.restart": AdministrativeTaskType(
        "bot.restart",
        "Restart bot",
        "bots.restart",
        CANONICAL_BOTS,
        misfire=MisfirePolicy.SKIP,
    ),
    "commands.sync": AdministrativeTaskType(
        "commands.sync",
        "Synchronize commands",
        "commands.sync",
        frozenset(TRUSTED_CAPABILITY_CATALOG),
        requires_ready=True,
    ),
}


@dataclass(frozen=True, slots=True)
class Schedule:
    kind: str
    timezone: str
    at: str | None = None
    local_time: str | None = None
    weekdays: tuple[int, ...] = ()
    interval_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    task_id: str
    name: str
    bot_id: str
    task_type_id: str
    owner_id: str
    enabled: bool
    schedule: Schedule
    parameters: Mapping[str, str]
    definition_version: int
    revision: int
    created_at: datetime
    updated_at: datetime
    next_run_at: datetime | None
    last_run_at: datetime | None
    suspended_reason: str | None = None
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TaskExecution:
    execution_id: str
    task_id: str
    occurrence: str
    planned_at: datetime
    started_at: datetime
    completed_at: datetime | None
    status: ExecutionStatus
    request_id: str
    operation_id: str | None = None
    result: str | None = None


@dataclass(frozen=True, slots=True)
class SchedulerAuditEvent:
    name: str
    timestamp: datetime
    actor: str
    bot_id: str
    task_id: str
    task_type_id: str
    request_id: str
    result: str
    execution_id: str | None = None
    operation_id: str | None = None
    initiated_by: str = "portal"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise SchedulerError("schedule_invalid", "A timezone-aware date is required.", 422)
    return value.astimezone(UTC)


def _zone(name: str) -> ZoneInfo:
    if len(name) > 64 or "/" not in name and name != "UTC":
        raise SchedulerError("timezone_invalid", "Timezone is invalid.", 422)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise SchedulerError("timezone_invalid", "Timezone is invalid.", 422) from None


def _local_candidate(day: date, local: time, zone: ZoneInfo) -> datetime | None:
    """Choose the first fold; reject nonexistent wall times by UTC round-trip."""
    candidate = datetime.combine(day, local, zone).replace(fold=0)
    returned = candidate.astimezone(UTC).astimezone(zone)
    if returned.replace(tzinfo=None) != candidate.replace(tzinfo=None):
        return None
    return candidate.astimezone(UTC)


def validate_schedule(schedule: Schedule, now: datetime) -> None:
    zone = _zone(schedule.timezone)
    if schedule.kind == "once":
        if not schedule.at or any(
            (schedule.local_time, schedule.weekdays, schedule.interval_seconds)
        ):
            raise SchedulerError("schedule_invalid", "One-time schedule is invalid.", 422)
        try:
            at = _utc(datetime.fromisoformat(schedule.at))
        except (ValueError, SchedulerError):
            raise SchedulerError("schedule_invalid", "One-time schedule is invalid.", 422) from None
        if at < _utc(now) - timedelta(minutes=1) or at > _utc(now) + MAX_HORIZON:
            raise SchedulerError(
                "schedule_invalid", "One-time date is outside the allowed horizon.", 422
            )
    elif schedule.kind in {"daily", "weekly"}:
        if not schedule.local_time or schedule.at or schedule.interval_seconds:
            raise SchedulerError("schedule_invalid", "Recurring schedule is invalid.", 422)
        try:
            time.fromisoformat(schedule.local_time)
        except ValueError:
            raise SchedulerError("schedule_invalid", "Local time is invalid.", 422) from None
        if schedule.kind == "daily" and schedule.weekdays:
            raise SchedulerError("schedule_invalid", "Daily schedule is invalid.", 422)
        if schedule.kind == "weekly" and (
            not schedule.weekdays
            or any(x not in range(7) for x in schedule.weekdays)
            or len(set(schedule.weekdays)) != len(schedule.weekdays)
        ):
            raise SchedulerError("schedule_invalid", "Weekdays are invalid.", 422)
    elif schedule.kind == "interval":
        if schedule.interval_seconds is None or schedule.interval_seconds < MIN_INTERVAL_SECONDS:
            raise SchedulerError("schedule_invalid", "Interval is below the platform minimum.", 422)
        if schedule.interval_seconds > int(MAX_HORIZON.total_seconds()) or any(
            (schedule.at, schedule.local_time, schedule.weekdays)
        ):
            raise SchedulerError("schedule_invalid", "Interval schedule is invalid.", 422)
    else:
        raise SchedulerError("schedule_invalid", "Schedule type is not supported.", 422)
    del zone


def next_run(schedule: Schedule, after: datetime, *, inclusive: bool = False) -> datetime | None:
    validate_schedule(schedule, after)
    after = _utc(after)
    if schedule.kind == "once":
        candidate = _utc(datetime.fromisoformat(schedule.at or ""))
        return candidate if candidate > after or (inclusive and candidate == after) else None
    if schedule.kind == "interval":
        return after + timedelta(seconds=schedule.interval_seconds or 0)
    zone, local = _zone(schedule.timezone), time.fromisoformat(schedule.local_time or "")
    local_day = after.astimezone(zone).date()
    for offset in range(0, 9):
        day = local_day + timedelta(days=offset)
        if schedule.kind == "weekly" and day.weekday() not in schedule.weekdays:
            continue
        candidate = _local_candidate(day, local, zone)
        if candidate is not None and (candidate > after or (inclusive and candidate == after)):
            return candidate
    raise SchedulerError("schedule_invalid", "No valid next occurrence was found.", 422)


class TaskAdapter(Protocol):
    async def execute(
        self, task: ScheduledTask, actor: Principal, request_id: str
    ) -> str | None: ...


class SQLiteSchedulerStore:
    """Transactional task definitions, durable occurrence claims, and bounded history."""

    def __init__(self, path: Path, *, history_per_task: int = 100) -> None:
        self.path, self.history_per_task = Path(path), max(1, min(history_per_task, 1000))
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.migrate()
        os.chmod(self.path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def migrate(self) -> None:
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS scheduler_schema(singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL)"
            )
            row = db.execute("SELECT version FROM scheduler_schema WHERE singleton=1").fetchone()
            version = 0 if row is None else int(row[0])
            if version > SCHEMA_VERSION:
                raise SchedulerError(
                    "scheduler_unavailable", "Scheduler schema is newer than supported.", 503
                )
            if version < 1:
                db.execute(
                    """CREATE TABLE scheduled_tasks(task_id TEXT PRIMARY KEY,name TEXT NOT NULL,bot_id TEXT NOT NULL,task_type_id TEXT NOT NULL,owner_id TEXT NOT NULL,enabled INTEGER NOT NULL,schedule_json TEXT NOT NULL,parameters_json TEXT NOT NULL,definition_version INTEGER NOT NULL,revision INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,next_run_at TEXT,last_run_at TEXT,suspended_reason TEXT,deleted_at TEXT)"""
                )
                db.execute(
                    """CREATE TABLE task_executions(execution_id TEXT PRIMARY KEY,task_id TEXT NOT NULL,occurrence TEXT NOT NULL,planned_at TEXT NOT NULL,started_at TEXT NOT NULL,completed_at TEXT,status TEXT NOT NULL,request_id TEXT NOT NULL,operation_id TEXT,result TEXT,UNIQUE(task_id,occurrence),FOREIGN KEY(task_id) REFERENCES scheduled_tasks(task_id))"""
                )
                db.execute(
                    "CREATE INDEX execution_task_idx ON task_executions(task_id,started_at DESC)"
                )
                db.execute(
                    """CREATE TABLE scheduler_lease(singleton INTEGER PRIMARY KEY CHECK(singleton=1),owner TEXT NOT NULL,expires_at TEXT NOT NULL)"""
                )
                db.execute("INSERT INTO scheduler_schema VALUES(1,1)")
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _task(row: sqlite3.Row) -> ScheduledTask:
        schedule = Schedule(**json.loads(row["schedule_json"]))

        def dt(key):
            return None if row[key] is None else datetime.fromisoformat(row[key])

        return ScheduledTask(
            row["task_id"],
            row["name"],
            row["bot_id"],
            row["task_type_id"],
            row["owner_id"],
            bool(row["enabled"]),
            schedule,
            json.loads(row["parameters_json"]),
            int(row["definition_version"]),
            int(row["revision"]),
            dt("created_at"),
            dt("updated_at"),
            dt("next_run_at"),
            dt("last_run_at"),
            row["suspended_reason"],
            dt("deleted_at"),
        )

    def get(self, task_id: str) -> ScheduledTask | None:
        if not ID_PATTERN.fullmatch(task_id):
            return None
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM scheduled_tasks WHERE task_id=? AND deleted_at IS NULL", (task_id,)
            ).fetchone()
        return None if row is None else self._task(row)

    def list(self) -> tuple[ScheduledTask, ...]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM scheduled_tasks WHERE deleted_at IS NULL ORDER BY created_at"
            ).fetchall()
        return tuple(self._task(x) for x in rows)

    def insert(self, task: ScheduledTask) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO scheduled_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task.task_id,
                    task.name,
                    task.bot_id,
                    task.task_type_id,
                    task.owner_id,
                    int(task.enabled),
                    json.dumps(asdict(task.schedule), separators=(",", ":")),
                    json.dumps(task.parameters, sort_keys=True, separators=(",", ":")),
                    task.definition_version,
                    task.revision,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    task.next_run_at.isoformat() if task.next_run_at else None,
                    None,
                    None,
                    None,
                ),
            )

    def update(self, task: ScheduledTask, expected: int) -> None:
        with self.connect() as db:
            result = db.execute(
                "UPDATE scheduled_tasks SET name=?,enabled=?,schedule_json=?,parameters_json=?,revision=?,updated_at=?,next_run_at=?,suspended_reason=?,deleted_at=? WHERE task_id=? AND revision=?",
                (
                    task.name,
                    int(task.enabled),
                    json.dumps(asdict(task.schedule), separators=(",", ":")),
                    json.dumps(task.parameters, sort_keys=True, separators=(",", ":")),
                    task.revision,
                    task.updated_at.isoformat(),
                    task.next_run_at.isoformat() if task.next_run_at else None,
                    task.suspended_reason,
                    task.deleted_at.isoformat() if task.deleted_at else None,
                    task.task_id,
                    expected,
                ),
            )
            if result.rowcount != 1:
                raise SchedulerError("stale_revision", "Task was concurrently modified.")

    def claim(
        self,
        task: ScheduledTask,
        planned: datetime,
        now: datetime,
        request_id: str,
        *,
        occurrence: str | None = None,
    ) -> TaskExecution | None:
        execution = TaskExecution(
            uuid.uuid4().hex,
            task.task_id,
            occurrence or planned.isoformat(),
            planned,
            now,
            None,
            ExecutionStatus.RUNNING,
            request_id,
        )
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO task_executions VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        execution.execution_id,
                        execution.task_id,
                        execution.occurrence,
                        planned.isoformat(),
                        now.isoformat(),
                        None,
                        execution.status.value,
                        request_id,
                        None,
                        None,
                    ),
                )
                db.execute(
                    "UPDATE scheduled_tasks SET last_run_at=? WHERE task_id=?",
                    (planned.isoformat(), task.task_id),
                )
        except sqlite3.IntegrityError:
            return None
        return execution

    def finish(
        self,
        execution: TaskExecution,
        status: ExecutionStatus,
        now: datetime,
        *,
        operation_id: str | None = None,
        result: str | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE task_executions SET completed_at=?,status=?,operation_id=?,result=? WHERE execution_id=?",
                (now.isoformat(), status.value, operation_id, result, execution.execution_id),
            )
            db.execute(
                "DELETE FROM task_executions WHERE execution_id IN (SELECT execution_id FROM task_executions WHERE task_id=? ORDER BY started_at DESC LIMIT -1 OFFSET ?)",
                (execution.task_id, self.history_per_task),
            )

    def history(self, task_id: str, limit: int = 20) -> tuple[TaskExecution, ...]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM task_executions WHERE task_id=? ORDER BY started_at DESC LIMIT ?",
                (task_id, min(max(limit, 1), 100)),
            ).fetchall()
        return tuple(
            TaskExecution(
                r["execution_id"],
                r["task_id"],
                r["occurrence"],
                datetime.fromisoformat(r["planned_at"]),
                datetime.fromisoformat(r["started_at"]),
                None if r["completed_at"] is None else datetime.fromisoformat(r["completed_at"]),
                ExecutionStatus(r["status"]),
                r["request_id"],
                r["operation_id"],
                r["result"],
            )
            for r in rows
        )

    def recover_running(self, now: datetime) -> int:
        with self.connect() as db:
            result = db.execute(
                "UPDATE task_executions SET completed_at=?,status=?,result=? WHERE status=?",
                (
                    now.isoformat(),
                    ExecutionStatus.UNKNOWN.value,
                    "completion_unknown",
                    ExecutionStatus.RUNNING.value,
                ),
            )
        return result.rowcount

    def acquire_lease(
        self, owner: str, now: datetime, duration: timedelta = timedelta(seconds=30)
    ) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT owner,expires_at FROM scheduler_lease WHERE singleton=1"
            ).fetchone()
            if row and row["owner"] != owner and datetime.fromisoformat(row["expires_at"]) > now:
                return False
            db.execute(
                "INSERT INTO scheduler_lease VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at",
                (owner, (now + duration).isoformat()),
            )
        return True

    def release_lease(self, owner: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM scheduler_lease WHERE owner=?", (owner,))


class SchedulerService:
    def __init__(
        self,
        store: SQLiteSchedulerStore,
        identities,
        authorizer,
        adapter: TaskAdapter,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        audit_sink: Callable[[SchedulerAuditEvent], None] | None = None,
        max_total: int = 200,
        max_per_owner_bot: int = 25,
    ) -> None:
        self.store, self.identities, self.authorizer, self.adapter = (
            store,
            identities,
            authorizer,
            adapter,
        )
        self.clock, self.audit_sink = clock, audit_sink
        self.max_total, self.max_per_owner_bot = max_total, max_per_owner_bot
        self._locks: set[str] = set()

    def _type(self, task_type_id: str) -> AdministrativeTaskType:
        value = ADMINISTRATIVE_TASK_CATALOG.get(task_type_id)
        if value is None:
            raise SchedulerError("task_type_not_supported", "Task type is not supported.", 404)
        return value

    def _require(self, actor: Principal, permission: str, bot_id: str) -> None:
        if not self.authorizer.can(actor, permission, bot_id=bot_id):
            raise SchedulerError("permission_denied", "Permission is denied.", 403)

    def _validate(
        self, bot_id: str, kind: AdministrativeTaskType, params: Mapping[str, str]
    ) -> None:
        if bot_id not in CANONICAL_BOTS or bot_id not in kind.supported_bots:
            raise SchedulerError(
                "capability_not_supported", "Task is not supported for this bot.", 422
            )
        if set(params) != set(kind.parameter_names) or any(
            not isinstance(x, str) or len(x) > 64 for x in params.values()
        ):
            raise SchedulerError("task_parameters_invalid", "Task parameters are invalid.", 422)
        if (
            kind.task_type_id == "backup.create"
            and (bot_id, params.get("plan_id", "")) not in TRUSTED_BACKUP_PLANS
        ):
            raise SchedulerError("task_parameters_invalid", "Backup plan is not supported.", 422)

    def list_tasks(self, actor: Principal) -> tuple[ScheduledTask, ...]:
        return tuple(
            t
            for t in self.store.list()
            if self.authorizer.can(actor, "scheduler.view", bot_id=t.bot_id)
        )

    def get_task(self, actor: Principal, task_id: str) -> ScheduledTask:
        task = self.store.get(task_id)
        if task is None or not self.authorizer.can(actor, "scheduler.view", bot_id=task.bot_id):
            raise SchedulerError("scheduled_task_not_found", "Scheduled task was not found.", 404)
        return task

    def create(
        self,
        actor: Principal,
        *,
        name: str,
        bot_id: str,
        task_type_id: str,
        schedule: Schedule,
        parameters: Mapping[str, str],
        enabled: bool = True,
        request_id: str = "",
    ) -> ScheduledTask:
        kind = self._type(task_type_id)
        self._require(actor, "scheduler.manage", bot_id)
        self._require(actor, kind.underlying_permission, bot_id)
        self._validate(bot_id, kind, parameters)
        if not SAFE_NAME.fullmatch(name):
            raise SchedulerError("schedule_invalid", "Task name is invalid.", 422)
        now = _utc(self.clock())
        validate_schedule(schedule, now)
        tasks = self.store.list()
        if (
            len(tasks) >= self.max_total
            or sum(t.owner_id == actor.principal_id and t.bot_id == bot_id for t in tasks)
            >= self.max_per_owner_bot
        ):
            raise SchedulerError(
                "scheduler_limit_reached", "Scheduler task limit was reached.", 429
            )
        task = ScheduledTask(
            uuid.uuid4().hex,
            name,
            bot_id,
            task_type_id,
            actor.principal_id,
            enabled,
            schedule,
            dict(parameters),
            kind.definition_version,
            1,
            now,
            now,
            next_run(schedule, now) if enabled else None,
            None,
        )
        self.store.insert(task)
        self._audit("task.created", actor.principal_id, task, request_id, "succeeded")
        return task

    def update(
        self,
        actor: Principal,
        task_id: str,
        revision: int,
        *,
        name: str,
        schedule: Schedule,
        parameters: Mapping[str, str],
        enabled: bool | None = None,
        request_id: str = "",
    ) -> ScheduledTask:
        old = self.get_task(actor, task_id)
        kind = self._type(old.task_type_id)
        self._require(actor, "scheduler.manage", old.bot_id)
        self._require(actor, kind.underlying_permission, old.bot_id)
        self._validate(old.bot_id, kind, parameters)
        if revision != old.revision:
            raise SchedulerError("stale_revision", "Task was concurrently modified.")
        if not SAFE_NAME.fullmatch(name):
            raise SchedulerError("schedule_invalid", "Task name is invalid.", 422)
        now = _utc(self.clock())
        validate_schedule(schedule, now)
        state = old.enabled if enabled is None else enabled
        task = ScheduledTask(
            old.task_id,
            name,
            old.bot_id,
            old.task_type_id,
            old.owner_id,
            state,
            schedule,
            dict(parameters),
            old.definition_version,
            old.revision + 1,
            old.created_at,
            now,
            next_run(schedule, now) if state else None,
            old.last_run_at,
            None,
            old.deleted_at,
        )
        self.store.update(task, revision)
        self._audit("task.updated", actor.principal_id, task, request_id, "succeeded")
        return task

    def set_enabled(
        self, actor: Principal, task_id: str, revision: int, enabled: bool, request_id: str = ""
    ) -> ScheduledTask:
        old = self.get_task(actor, task_id)
        task = self.update(
            actor,
            task_id,
            revision,
            name=old.name,
            schedule=old.schedule,
            parameters=old.parameters,
            enabled=enabled,
            request_id=request_id,
        )
        self._audit(
            "task.enabled" if enabled else "task.disabled",
            actor.principal_id,
            task,
            request_id,
            "succeeded",
        )
        return task

    def delete(self, actor: Principal, task_id: str, revision: int, request_id: str = "") -> None:
        old = self.get_task(actor, task_id)
        kind = self._type(old.task_type_id)
        self._require(actor, "scheduler.manage", old.bot_id)
        self._require(actor, kind.underlying_permission, old.bot_id)
        if revision != old.revision:
            raise SchedulerError("stale_revision", "Task was concurrently modified.")
        now = _utc(self.clock())
        deleted = ScheduledTask(
            **{
                **asdict(old),
                "schedule": old.schedule,
                "revision": old.revision + 1,
                "enabled": False,
                "updated_at": now,
                "next_run_at": None,
                "deleted_at": now,
            }
        )
        self.store.update(deleted, revision)
        self._audit("task.deleted", actor.principal_id, old, request_id, "succeeded")

    async def run_now(self, actor: Principal, task_id: str, request_id: str) -> TaskExecution:
        task = self.get_task(actor, task_id)
        if not task.enabled:
            raise SchedulerError("task_disabled", "Scheduled task is disabled.")
        kind = self._type(task.task_type_id)
        self._require(actor, "scheduler.run", task.bot_id)
        self._require(actor, kind.underlying_permission, task.bot_id)
        self._audit("task.run_now_requested", actor.principal_id, task, request_id, "requested")
        return await self._execute(task, _utc(self.clock()), request_id, manual_actor=actor)

    async def run_due(self) -> tuple[TaskExecution, ...]:
        now = _utc(self.clock())
        results = []
        for task in self.store.list():
            if task.enabled and task.next_run_at and task.next_run_at <= now:
                planned = task.next_run_at
                results.append(await self._execute(task, planned, uuid.uuid4().hex))
                current = self.store.get(task.task_id)
                if current:
                    next_at = (
                        next_run(task.schedule, planned) if task.schedule.kind != "once" else None
                    )
                    updated = ScheduledTask(
                        **{
                            **asdict(current),
                            "schedule": current.schedule,
                            "enabled": current.enabled and next_at is not None,
                            "next_run_at": next_at,
                            "revision": current.revision + 1,
                            "updated_at": now,
                        }
                    )
                    self.store.update(updated, current.revision)
        return tuple(results)

    async def _execute(
        self,
        task: ScheduledTask,
        planned: datetime,
        request_id: str,
        manual_actor: Principal | None = None,
    ) -> TaskExecution:
        now = _utc(self.clock())
        kind = self._type(task.task_type_id)
        claimed = self.store.claim(
            task,
            planned,
            now,
            request_id,
            occurrence=(f"manual:{uuid.uuid4().hex}" if manual_actor else None),
        )
        if claimed is None:
            raise SchedulerError("execution_conflict", "Occurrence was already claimed.")
        if task.task_id in self._locks:
            self.store.finish(claimed, ExecutionStatus.CONFLICT, now, result="overlap_forbidden")
            return claimed
        missed = now > planned
        if not manual_actor and (
            (kind.misfire is MisfirePolicy.SKIP and missed)
            or now - planned > timedelta(seconds=kind.grace_seconds)
        ):
            self.store.finish(claimed, ExecutionStatus.MISFIRED, now, result="misfire_skipped")
            return claimed
        identity = self.identities.find_by_id(task.owner_id)
        actor = manual_actor or (identity.principal() if identity and identity.enabled else None)
        scheduler_permission = "scheduler.run" if manual_actor else "scheduler.manage"
        if (
            actor is None
            or not self.authorizer.can(actor, scheduler_permission, bot_id=task.bot_id)
            or not self.authorizer.can(actor, kind.underlying_permission, bot_id=task.bot_id)
            or task.definition_version != kind.definition_version
        ):
            self.store.finish(
                claimed, ExecutionStatus.AUTHORIZATION_REVOKED, now, result="authorization_revoked"
            )
            self._suspend(task, "authorization_revoked")
            self._audit(
                "task.execution_authorization_revoked",
                task.owner_id,
                task,
                request_id,
                "authorization_revoked",
                claimed.execution_id,
                initiated_by="scheduler",
            )
            return claimed
        try:
            self._validate(task.bot_id, kind, task.parameters)
        except SchedulerError:
            self.store.finish(
                claimed,
                ExecutionStatus.CAPABILITY_UNAVAILABLE,
                now,
                result="capability_not_supported",
            )
            self._suspend(task, "capability_not_supported")
            return claimed
        self._locks.add(task.task_id)
        self._audit(
            "task.execution_started",
            task.owner_id,
            task,
            request_id,
            "running",
            claimed.execution_id,
            initiated_by="scheduler",
        )
        try:
            operation_id = await self.adapter.execute(task, actor, request_id)
            self.store.finish(
                claimed,
                ExecutionStatus.SUCCEEDED,
                _utc(self.clock()),
                operation_id=operation_id,
                result="succeeded",
            )
            self._audit(
                "task.execution_succeeded",
                task.owner_id,
                task,
                request_id,
                "succeeded",
                claimed.execution_id,
                operation_id,
                initiated_by="scheduler",
            )
        except Exception:
            self.store.finish(
                claimed,
                ExecutionStatus.FAILED,
                _utc(self.clock()),
                result="underlying_operation_failed",
            )
            self._audit(
                "task.execution_failed",
                task.owner_id,
                task,
                request_id,
                "failed",
                claimed.execution_id,
                initiated_by="scheduler",
            )
        finally:
            self._locks.discard(task.task_id)
        return claimed

    def _suspend(self, task: ScheduledTask, reason: str) -> None:
        current = self.store.get(task.task_id)
        if current:
            changed = ScheduledTask(
                **{
                    **asdict(current),
                    "schedule": current.schedule,
                    "enabled": False,
                    "next_run_at": None,
                    "suspended_reason": reason,
                    "revision": current.revision + 1,
                    "updated_at": _utc(self.clock()),
                }
            )
            self.store.update(changed, current.revision)

    def _audit(
        self,
        name,
        actor,
        task,
        request_id,
        result,
        execution_id=None,
        operation_id=None,
        initiated_by="portal",
    ):
        if self.audit_sink:
            self.audit_sink(
                SchedulerAuditEvent(
                    name,
                    _utc(self.clock()),
                    actor,
                    task.bot_id,
                    task.task_id,
                    task.task_type_id,
                    request_id,
                    result,
                    execution_id,
                    operation_id,
                    initiated_by,
                )
            )


class PlatformTaskAdapter:
    """Routes catalog actions through the existing Stage 7/12/14 services."""

    def __init__(self, management, backups) -> None:
        self.management, self.backups = management, backups

    async def execute(self, task: ScheduledTask, actor: Principal, request_id: str) -> str | None:
        if task.task_type_id == "backup.create":
            return self.backups.create_backup(
                actor, task.bot_id, task.parameters["plan_id"], request_id
            ).operation_id
        if task.task_type_id == "bot.restart":
            return (
                await self.management.lifecycle(actor, task.bot_id, "restart")
            ).operation.operation_id
        if task.task_type_id == "commands.sync":
            return (
                await self.management.sync_commands(actor, task.bot_id, request_id)
            ).operation_id
        raise SchedulerError("task_type_not_supported", "Task type is not supported.", 404)


class SchedulerRunner:
    """Single-owner bounded polling lifecycle, intended for one dedicated local process."""

    def __init__(self, service: SchedulerService, *, interval: float = 5.0) -> None:
        self.service, self.interval, self.owner = service, interval, uuid.uuid4().hex
        self._stop = False

    async def run(self) -> None:
        now = _utc(self.service.clock())
        self.service.store.recover_running(now)
        while not self._stop:
            now = _utc(self.service.clock())
            if self.service.store.acquire_lease(self.owner, now):
                await self.service.run_due()
            await asyncio.sleep(self.interval)
        self.service.store.release_lease(self.owner)

    def stop(self) -> None:
        self._stop = True
