"""Async, typed process-lifecycle service independent of HTTP and Discord."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
import time
from collections.abc import Callable, Mapping

from .controller import SubprocessController, linux_process_identity
from .errors import (
    BotAlreadyRunningError,
    BotAlreadyStoppedError,
    BotDisabledError,
    OperationInProgressError,
    ProcessIdentityError,
    ProcessStartError,
    SupervisorClosedError,
    SupervisorError,
)
from .models import (
    AuditEvent,
    LifecycleAction,
    LifecycleResult,
    OperationRecord,
    OperationStatus,
    ProcessRecord,
    ProcessState,
    RegisteredBot,
    utcnow,
)
from .registry import BotRegistry
from .state import StateStore
from .health import DesiredState, HealthEvidence, HealthStore, HealthTiming, HeartbeatReceiver

logger = logging.getLogger(__name__)
SAFE_ENVIRONMENT = frozenset({"PATH", "HOME", "LANG", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR"})


class SupervisorService:
    def __init__(
        self,
        registry: BotRegistry,
        state_store: StateStore,
        *,
        controller: SubprocessController | None = None,
        environment: Mapping[str, str] | None = None,
        startup_grace_seconds: float = 0.15,
        event_sink: Callable[[AuditEvent], None] | None = None,
        health_timing: HealthTiming = HealthTiming(),
    ) -> None:
        self.registry = registry
        self.state_store = state_store
        self.controller = controller or SubprocessController()
        self._environment = dict(os.environ if environment is None else environment)
        self._startup_grace = startup_grace_seconds
        self._event_sink = event_sink
        self._records: dict[str, ProcessRecord] = {}
        self._operations: dict[str, OperationRecord] = {}
        self._locks = {bot.bot_id: asyncio.Lock() for bot in registry.list()}
        self._accepting = False
        self.health = HealthStore(health_timing, monotonic=time.monotonic)
        self._heartbeat_receiver = HeartbeatReceiver(
            str(self.state_store.path.parent / "heartbeat.sock"),
            self.health,
            frozenset(bot.bot_id for bot in registry.list()),
        )

    async def startup(self) -> None:
        self._records.clear()
        for saved in self.state_store.load():
            try:
                bot = self.registry.get(saved.bot_id)
            except SupervisorError:
                continue
            evidence = linux_process_identity(saved.pid)
            if evidence is None:
                continue
            ticks, argv = evidence
            if ticks == saved.os_start_ticks and argv == saved.expected_argv:
                saved.state = ProcessState.RUNNING
            else:
                # Retain conflict evidence but never signal or adopt the process.
                saved.state = ProcessState.UNKNOWN
            saved.adopted = saved.state is ProcessState.RUNNING
            self._records[bot.bot_id] = saved
        self._persist()
        self._accepting = True
        for bot in self.registry.list():
            record = self._records.get(bot.bot_id)
            await self.health.set_evidence(
                HealthEvidence(
                    bot.bot_id,
                    bot.enabled,
                    DesiredState.RUNNING if record else DesiredState.STOPPED,
                    bool(record and record.state is ProcessState.RUNNING),
                    bool(record and record.adopted),
                    record.process_instance_id if record else None,
                    time.monotonic() if record and record.state is ProcessState.RUNNING else None,
                    process_conflict=bool(record and record.state is ProcessState.UNKNOWN),
                )
            )
        await self._heartbeat_receiver.start()

    async def shutdown(self) -> None:
        self._accepting = False
        self._persist()
        await self._heartbeat_receiver.close()
        await self.controller.close()

    def list_bots(self) -> tuple[RegisteredBot, ...]:
        return self.registry.list()

    def get_bot(self, bot_id: str) -> RegisteredBot:
        return self.registry.get(bot_id)

    def get_process_state(self, bot_id: str) -> ProcessState:
        bot = self.registry.get(bot_id)
        record = self._records.get(bot_id)
        if record is not None:
            return record.state
        return ProcessState.OFFLINE if bot.enabled else ProcessState.DISABLED

    def get_process(self, bot_id: str) -> ProcessRecord | None:
        self.registry.get(bot_id)
        return self._records.get(bot_id)

    def get_operation(self, operation_id: str) -> OperationRecord | None:
        return self._operations.get(operation_id)

    async def start(self, bot_id: str, *, actor: str | None = None) -> LifecycleResult:
        return await self._operate(bot_id, LifecycleAction.START, actor, self._start_locked)

    async def stop(self, bot_id: str, *, actor: str | None = None) -> LifecycleResult:
        return await self._operate(bot_id, LifecycleAction.STOP, actor, self._stop_locked)

    async def restart(self, bot_id: str, *, actor: str | None = None) -> LifecycleResult:
        return await self._operate(bot_id, LifecycleAction.RESTART, actor, self._restart_locked)

    async def _operate(self, bot_id, action, actor, implementation):
        if not self._accepting:
            raise SupervisorClosedError("supervisor is not accepting operations")
        bot = self.registry.get(bot_id)
        lock = self._locks[bot_id]
        if lock.locked():
            raise OperationInProgressError(f"an operation is in progress for {bot_id}")
        operation = OperationRecord(str(uuid.uuid4()), bot_id, action, utcnow(), actor=actor)
        self._operations[operation.operation_id] = operation
        self._emit(f"bot.{action.value}.requested", operation)
        previous = self.get_process_state(bot_id)
        async with lock:
            operation.status = OperationStatus.RUNNING
            operation.started_at = utcnow()
            try:
                instance_id = await implementation(bot)
                operation.status = OperationStatus.SUCCEEDED
                self._emit(f"bot.{action.value}.succeeded", operation, instance_id)
                return LifecycleResult(
                    operation, previous, self.get_process_state(bot_id), instance_id
                )
            except SupervisorError as exc:
                operation.status = OperationStatus.FAILED
                operation.error_category = exc.code
                self._emit(f"bot.{action.value}.failed", operation, error=exc.code)
                raise
            finally:
                operation.completed_at = utcnow()

    async def _start_locked(self, bot: RegisteredBot) -> str:
        if not bot.enabled:
            raise BotDisabledError(f"{bot.bot_id} is disabled")
        current = self._records.get(bot.bot_id)
        if current and current.state in {
            ProcessState.STARTING,
            ProcessState.RUNNING,
            ProcessState.RESTARTING,
            ProcessState.STOPPING,
            ProcessState.UNKNOWN,
        }:
            raise BotAlreadyRunningError(f"{bot.bot_id} is not safely offline")
        token = self._environment.get(bot.token_environment_variable)
        if not token:
            raise ProcessStartError(
                f"required environment variable {bot.token_environment_variable} is missing"
            )
        if not bot.executable.is_file() or not os.access(bot.executable, os.X_OK):
            raise ProcessStartError("configured Python executable is unavailable")
        bot.runtime_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        instance_id = str(uuid.uuid4())
        argv = (str(bot.executable), "-m", bot.entry_point)
        environment = {
            key: value for key, value in self._environment.items() if key in SAFE_ENVIRONMENT
        }
        environment.update(
            {
                bot.token_environment_variable: token,
                "MDBO_RUNTIME_ROOT": str(bot.runtime_directory.parent),
                "MDBO_PROCESS_INSTANCE_ID": instance_id,
                "MDBO_HEARTBEAT_SOCKET": str(self.state_store.path.parent / "heartbeat.sock"),
            }
        )
        record = ProcessRecord(
            bot.bot_id,
            instance_id,
            0,
            utcnow(),
            0,
            argv,
            ProcessState.STARTING,
        )
        self._records[bot.bot_id] = record
        try:
            process = await self.controller.spawn(
                record, argv, bot.working_directory, environment, self._process_exited
            )
            record.pid = process.pid
            await asyncio.sleep(self._startup_grace)
            if process.returncode is not None:
                raise ProcessStartError(
                    f"process exited during startup with code {process.returncode}"
                )
            evidence = linux_process_identity(process.pid)
            if evidence is None:
                raise ProcessStartError("could not establish process identity")
            record.os_start_ticks, record.expected_argv = evidence
            record.state = ProcessState.RUNNING
            self._persist()
            await self.health.set_evidence(
                HealthEvidence(
                    bot.bot_id,
                    True,
                    DesiredState.RUNNING,
                    True,
                    True,
                    instance_id,
                    time.monotonic(),
                )
            )
            return instance_id
        except (OSError, ProcessStartError) as exc:
            record.state = ProcessState.CRASHED
            self._persist()
            if isinstance(exc, ProcessStartError):
                raise
            raise ProcessStartError("could not start configured process") from exc

    async def _stop_locked(self, bot: RegisteredBot) -> str | None:
        record = self._records.get(bot.bot_id)
        if record is None or record.state in {ProcessState.OFFLINE, ProcessState.DISABLED}:
            raise BotAlreadyStoppedError(f"{bot.bot_id} is already stopped")
        self._verify_identity(record)
        record.state = ProcessState.STOPPING
        record.expected_exit = True
        await self.controller.terminate(record)
        try:
            await self.controller.wait_for_exit(record, bot.shutdown_timeout_seconds)
        except TimeoutError:
            self._verify_identity(record)
            record.forced = True
            await self.controller.kill(record)
            await self.controller.wait_for_exit(record, min(5.0, bot.shutdown_timeout_seconds))
        record.state = ProcessState.OFFLINE
        self._persist()
        await self.health.set_evidence(
            HealthEvidence(
                bot.bot_id,
                bot.enabled,
                DesiredState.STOPPED,
                False,
                True,
                record.process_instance_id,
                None,
            )
        )
        return record.process_instance_id

    async def _restart_locked(self, bot: RegisteredBot) -> str:
        record = self._records.get(bot.bot_id)
        if record and record.state not in {ProcessState.OFFLINE, ProcessState.CRASHED}:
            record.state = ProcessState.RESTARTING
            await self._stop_locked(bot)
        return await self._start_locked(bot)

    def _verify_identity(self, record: ProcessRecord) -> None:
        evidence = linux_process_identity(record.pid)
        if evidence != (record.os_start_ticks, record.expected_argv):
            record.state = ProcessState.UNKNOWN
            self._persist()
            raise ProcessIdentityError("process identity evidence does not match")

    async def _process_exited(self, record: ProcessRecord, code: int) -> None:
        record.exit_code = code
        record.exited_at = utcnow()
        if record.expected_exit:
            record.state = ProcessState.OFFLINE
        else:
            record.state = ProcessState.CRASHED
        self._persist()
        bot = self.registry.get(record.bot_id)
        await self.health.set_evidence(
            HealthEvidence(
                record.bot_id,
                bot.enabled,
                DesiredState.STOPPED if record.expected_exit else DesiredState.RUNNING,
                False,
                True,
                record.process_instance_id,
                None,
                unexpected_exit=not record.expected_exit,
            )
        )
        self._emit(
            "bot.process.exited", instance_id=record.process_instance_id, bot_id=record.bot_id
        )

    def _persist(self) -> None:
        self.state_store.save(list(self._records.values()))

    def _emit(self, name, operation=None, instance_id=None, error=None, bot_id=None):
        if self._event_sink is None:
            return
        self._event_sink(
            AuditEvent(
                name,
                utcnow(),
                bot_id or operation.bot_id,
                operation.operation_id if operation else None,
                instance_id,
                operation.actor if operation else None,
                error,
            )
        )
