"""Closed, typed Stage 12 bot-application operation boundary.

This module deliberately knows no Discord or bot business packages.  An adapter is
provided by the running bot control transport; all browser input is resolved against
the immutable catalogs below before that adapter is called.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol

from supervisor.health import HealthSnapshot
from supervisor.models import ProcessState

COG_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
MAX_COG_ID_LENGTH = 64
DEFAULT_HISTORY_LIMIT = 20
MAX_HISTORY_LIMIT = 100


class Capability(StrEnum):
    COGS_VIEW = "cogs.view"
    COGS_LOAD = "cogs.load"
    COGS_UNLOAD = "cogs.unload"
    COGS_RELOAD = "cogs.reload"
    COGS_RELOAD_ALL = "cogs.reload_all"
    COMMANDS_SYNC = "commands.sync"
    MAINTENANCE_VIEW = "maintenance.view"
    MAINTENANCE_ENABLE = "maintenance.enable"
    MAINTENANCE_DISABLE = "maintenance.disable"


class ApplicationOperationType(StrEnum):
    COG_LOAD = "cog.load"
    COG_UNLOAD = "cog.unload"
    COG_RELOAD = "cog.reload"
    COGS_RELOAD_ALL = "cogs.reload_all"
    COMMANDS_SYNC = "commands.sync"
    MAINTENANCE_ENABLE = "maintenance.enable"
    MAINTENANCE_DISABLE = "maintenance.disable"


class ApplicationOperationStatus(StrEnum):
    REQUESTED = "requested"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CogDefinition:
    cog_id: str
    display_name: str
    extension: str
    description: str
    loadable: bool = True
    unloadable: bool = True
    reloadable: bool = True
    required: bool = False
    dependencies: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class BotCapabilityDefinition:
    bot_id: str
    capabilities: frozenset[Capability]
    cogs: Mapping[str, CogDefinition]
    command_scope: str | None = None
    maintenance_persists_restart: bool = False


@dataclass(frozen=True, slots=True)
class CogStatus:
    cog_id: str
    display_name: str
    description: str
    loaded: bool
    loadable: bool
    unloadable: bool
    reloadable: bool
    required: bool


@dataclass(frozen=True, slots=True)
class ReloadAllResult:
    successful: tuple[str, ...]
    failed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CommandSyncResult:
    command_count: int
    scope: str


@dataclass(slots=True)
class ApplicationOperation:
    operation_id: str
    request_id: str
    bot_id: str
    process_instance_id: str
    operation_type: ApplicationOperationType
    requested_at: datetime
    status: ApplicationOperationStatus = ApplicationOperationStatus.REQUESTED
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cog_id: str | None = None
    result_summary: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ApplicationAuditEvent:
    name: str
    timestamp: datetime
    request_id: str
    actor: str
    bot_id: str
    operation_id: str | None
    result: str
    cog_id: str | None = None


class ApplicationOperationError(Exception):
    """Bounded error whose message is always safe to return to an operator."""

    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.safe_message, self.status = code, message, status


class BotControlAdapter(Protocol):
    """Narrow bot-side contract; implementations must be local and instance-bound."""

    async def list_loaded_cogs(self, bot_id: str, process_instance_id: str) -> frozenset[str]: ...
    async def load_cog(self, bot_id: str, process_instance_id: str, extension: str) -> None: ...
    async def unload_cog(self, bot_id: str, process_instance_id: str, extension: str) -> None: ...
    async def reload_cog(self, bot_id: str, process_instance_id: str, extension: str) -> None: ...
    async def sync_commands(self, bot_id: str, process_instance_id: str) -> int: ...
    async def get_maintenance(self, bot_id: str, process_instance_id: str) -> bool: ...
    async def set_maintenance(
        self, bot_id: str, process_instance_id: str, enabled: bool
    ) -> None: ...


class OperationSupervisor(Protocol):
    def get_bot(self, bot_id: str): ...
    def get_process_state(self, bot_id: str) -> ProcessState: ...
    def get_process(self, bot_id: str): ...


class OperationHealthReader(Protocol):
    async def get(self, bot_id: str, *, refresh: bool = True) -> HealthSnapshot | None: ...


class OperationAuthorizer(Protocol):
    def can(self, actor, permission: str, *, bot_id: str | None = None) -> bool: ...


def _cogs(package: str, names: tuple[str, ...], *, protected: frozenset[str] = frozenset()):
    result: dict[str, CogDefinition] = {}
    for name in names:
        cog_id = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
        required = cog_id in protected
        result[cog_id] = CogDefinition(
            cog_id,
            name.replace("Cog", "").replace("Misc", ""),
            f"{package}.cogs.{name}",
            f"{name.replace('Cog', '')} bot feature.",
            loadable=not required,
            unloadable=not required,
            reloadable=not required,
            required=required,
        )
    return result


_COG_CAPABILITIES = frozenset(
    {
        Capability.COGS_VIEW,
        Capability.COGS_LOAD,
        Capability.COGS_UNLOAD,
        Capability.COGS_RELOAD,
        Capability.COGS_RELOAD_ALL,
        Capability.COMMANDS_SYNC,
    }
)

# Audited from each migrated bot's setup-bearing extensions.  Internal extension
# strings never cross the service boundary or appear in views/audits.
TRUSTED_CAPABILITY_CATALOG: Mapping[str, BotCapabilityDefinition] = {
    "cda-admin": BotCapabilityDefinition(
        "cda-admin",
        _COG_CAPABILITIES,
        _cogs(
            "cda_admin",
            (
                "AdminManager",
                "AwaitingVerificationCleanup",
                "BotCheck",
                "CogsLoader",
                "DailyAnnouncement",
                "LeaveCommand",
                "MessageDelete",
                "NameChange",
                "NoahAuditLog",
                "NoahInfo",
                "NoahPing",
                "NoahPurge",
                "RoleUpdater",
                "ServerPayAnnounce",
                "ServerUnVerify",
                "ServerVerify",
                "ServerVerifyBan",
                "TwoWayMessage",
                "UserInfo",
                "VerifiedRoleAudit",
                "VerifyKick",
                "delcha",
                "nem",
                "nice",
            ),
            protected=frozenset({"admin-manager", "cogs-loader"}),
        ),
        "global",
    ),
    "cda-pay": BotCapabilityDefinition(
        "cda-pay",
        _COG_CAPABILITIES,
        _cogs(
            "cda_pay",
            (
                "LeaveCommand",
                "MessageDelete",
                "NoahAuditLog",
                "NoahPing",
                "PayBackup",
                "PayLookup",
                "PayVoid",
                "RecordPay",
                "TwoWayMessage",
            ),
        ),
        "global",
    ),
    "unbot": BotCapabilityDefinition(
        "unbot",
        _COG_CAPABILITIES,
        _cogs("unbot", ("HabboIdTracker", "HabboProfileWatcher", "HabboUsernameFinder")),
        "global",
    ),
    "rpa-admin": BotCapabilityDefinition(
        "rpa-admin",
        _COG_CAPABILITIES,
        _cogs(
            "rpa_admin",
            (
                "AutoInviteCog",
                "HabboOnlineTimeCog",
                "MentionForwardCog",
                "MiscBan",
                "MiscGiveaway",
                "MiscKick",
                "MiscMute",
                "MiscProfanity",
                "MiscPurge",
                "MiscRaffle",
                "PayAnnounceCog",
                "PayVoidCog",
                "ReactionRoleCog",
                "ServerAuditLog",
                "ServerAutoRolesRPA",
                "ServerEmbedMaker",
                "ServerRules",
                "ServerSpecialUnit",
                "ServerSterileChannel",
                "ServerVerifyRPA",
                "UserNameChange",
                "UserVerifyRestrict",
                "WebhookApplicationChannelCog",
            ),
        ),
        "global",
    ),
}


class BotOperationService:
    """Authorization, prerequisites, serialization, instance binding and safe records."""

    def __init__(
        self,
        supervisor: OperationSupervisor,
        health: OperationHealthReader,
        authorizer: OperationAuthorizer,
        adapter: BotControlAdapter,
        *,
        catalog: Mapping[str, BotCapabilityDefinition] = TRUSTED_CAPABILITY_CATALOG,
        audit_sink: Callable[[ApplicationAuditEvent], None] | None = None,
        history_size: int = MAX_HISTORY_LIMIT,
    ) -> None:
        self._supervisor, self._health, self._authorizer, self._adapter = (
            supervisor,
            health,
            authorizer,
            adapter,
        )
        self._catalog, self._audit_sink = dict(catalog), audit_sink
        shared_lock = getattr(supervisor, "application_operation_lock", None)
        self._locks = {
            bot_id: shared_lock(bot_id) if shared_lock else asyncio.Lock() for bot_id in catalog
        }
        self._operations: dict[str, ApplicationOperation] = {}
        self._history: deque[str] = deque(maxlen=min(max(history_size, 1), MAX_HISTORY_LIMIT))

    def capabilities(self, actor, bot_id: str) -> frozenset[Capability]:
        definition = self._definition(bot_id)
        visible = set()
        for capability in definition.capabilities:
            permission = self._permission(capability)
            if self._authorizer.can(actor, permission, bot_id=bot_id):
                visible.add(capability)
        return frozenset(visible)

    async def list_cogs(self, actor, bot_id: str) -> tuple[CogStatus, ...]:
        definition = self._authorize(actor, bot_id, Capability.COGS_VIEW, "cogs.view")
        instance = await self._prerequisites(bot_id, ready=False)
        try:
            loaded_extensions = await self._adapter.list_loaded_cogs(bot_id, instance)
        except Exception:
            raise self._transport_error() from None
        # The adapter reports internal names, but only catalog matches are projected.
        return tuple(
            CogStatus(
                cog.cog_id,
                cog.display_name,
                cog.description,
                cog.extension in loaded_extensions,
                cog.loadable,
                cog.unloadable,
                cog.reloadable,
                cog.required,
            )
            for cog in definition.cogs.values()
        )

    async def load_cog(
        self, actor, bot_id: str, cog_id: str, request_id: str
    ) -> ApplicationOperation:
        return await self._cog_operation(
            actor,
            bot_id,
            cog_id,
            request_id,
            Capability.COGS_LOAD,
            ApplicationOperationType.COG_LOAD,
        )

    async def unload_cog(
        self, actor, bot_id: str, cog_id: str, request_id: str
    ) -> ApplicationOperation:
        return await self._cog_operation(
            actor,
            bot_id,
            cog_id,
            request_id,
            Capability.COGS_UNLOAD,
            ApplicationOperationType.COG_UNLOAD,
        )

    async def reload_cog(
        self, actor, bot_id: str, cog_id: str, request_id: str
    ) -> ApplicationOperation:
        return await self._cog_operation(
            actor,
            bot_id,
            cog_id,
            request_id,
            Capability.COGS_RELOAD,
            ApplicationOperationType.COG_RELOAD,
        )

    async def reload_all_cogs(self, actor, bot_id: str, request_id: str) -> ApplicationOperation:
        definition = self._authorize(actor, bot_id, Capability.COGS_RELOAD_ALL, "cogs.manage")
        operation = await self._begin(
            actor, bot_id, request_id, ApplicationOperationType.COGS_RELOAD_ALL
        )
        async with self._lock(bot_id, operation):
            successful, failed = [], []
            for cog in definition.cogs.values():
                if not cog.reloadable:
                    continue
                try:
                    await self._adapter.reload_cog(
                        bot_id, operation.process_instance_id, cog.extension
                    )
                    await self._verify_instance(bot_id, operation.process_instance_id)
                    successful.append(cog.cog_id)
                except ApplicationOperationError as exc:
                    self._fail(actor, operation, exc.code)
                    raise
                except Exception:
                    failed.append(cog.cog_id)
            result = ReloadAllResult(tuple(successful), tuple(failed))
            operation.result_summary = (
                f"{len(result.successful)} succeeded; {len(result.failed)} failed"
            )
            operation.status = (
                ApplicationOperationStatus.PARTIAL
                if failed
                else ApplicationOperationStatus.SUCCEEDED
            )
        self._complete(actor, operation)
        return operation

    async def sync_commands(self, actor, bot_id: str, request_id: str) -> ApplicationOperation:
        definition = self._authorize(actor, bot_id, Capability.COMMANDS_SYNC, "commands.sync")
        operation = await self._begin(
            actor, bot_id, request_id, ApplicationOperationType.COMMANDS_SYNC, ready=True
        )
        async with self._lock(bot_id, operation):
            try:
                count = await self._adapter.sync_commands(bot_id, operation.process_instance_id)
                await self._verify_instance(bot_id, operation.process_instance_id)
            except ApplicationOperationError:
                raise
            except Exception:
                self._fail(actor, operation, "command_sync_failed")
                raise ApplicationOperationError(
                    "command_sync_failed", "Command synchronization failed.", 502
                ) from None
            result = CommandSyncResult(max(0, int(count)), definition.command_scope or "configured")
            operation.result_summary = (
                f"{result.command_count} commands synchronized ({result.scope})"
            )
            operation.status = ApplicationOperationStatus.SUCCEEDED
        self._complete(actor, operation)
        return operation

    async def get_maintenance(self, actor, bot_id: str) -> bool:
        self._authorize(actor, bot_id, Capability.MAINTENANCE_VIEW, "maintenance.view")
        instance = await self._prerequisites(bot_id, ready=False)
        try:
            return await self._adapter.get_maintenance(bot_id, instance)
        except Exception:
            raise self._transport_error() from None

    async def enable_maintenance(self, actor, bot_id: str, request_id: str) -> ApplicationOperation:
        return await self._set_maintenance(actor, bot_id, request_id, True)

    async def disable_maintenance(
        self, actor, bot_id: str, request_id: str
    ) -> ApplicationOperation:
        return await self._set_maintenance(actor, bot_id, request_id, False)

    def get_operation(self, actor, operation_id: str) -> ApplicationOperation:
        if len(operation_id) > 64:
            raise ApplicationOperationError("operation_not_found", "Operation was not found.", 404)
        operation = self._operations.get(operation_id)
        if operation is None or not self._authorizer.can(
            actor, "operations.view", bot_id=operation.bot_id
        ):
            raise ApplicationOperationError("operation_not_found", "Operation was not found.", 404)
        return replace(operation)

    def recent_operations(
        self, actor, bot_id: str, limit: int = DEFAULT_HISTORY_LIMIT
    ) -> tuple[ApplicationOperation, ...]:
        self._supervisor.get_bot(bot_id)
        if not self._authorizer.can(actor, "operations.view", bot_id=bot_id):
            raise ApplicationOperationError("permission_denied", "Permission is denied.", 403)
        bounded = min(max(limit, 1), MAX_HISTORY_LIMIT)
        values = (self._operations[key] for key in reversed(self._history))
        return tuple(replace(item) for item in values if item.bot_id == bot_id)[:bounded]

    async def _cog_operation(self, actor, bot_id, cog_id, request_id, capability, operation_type):
        definition = self._authorize(actor, bot_id, capability, "cogs.manage")
        cog = self._resolve_cog(definition, cog_id)
        allowed = {
            ApplicationOperationType.COG_LOAD: cog.loadable,
            ApplicationOperationType.COG_UNLOAD: cog.unloadable,
            ApplicationOperationType.COG_RELOAD: cog.reloadable,
        }[operation_type]
        if not allowed:
            suffix = operation_type.value.split(".")[-1]
            raise ApplicationOperationError(f"cog_not_{suffix}able", f"Cog cannot be {suffix}ed.")
        operation = await self._begin(actor, bot_id, request_id, operation_type, cog_id=cog.cog_id)
        async with self._lock(bot_id, operation):
            try:
                loaded = await self._adapter.list_loaded_cogs(bot_id, operation.process_instance_id)
                if operation_type is ApplicationOperationType.COG_LOAD and cog.extension in loaded:
                    raise ApplicationOperationError("cog_already_loaded", "Cog is already loaded.")
                if (
                    operation_type
                    in {ApplicationOperationType.COG_UNLOAD, ApplicationOperationType.COG_RELOAD}
                    and cog.extension not in loaded
                ):
                    raise ApplicationOperationError("cog_not_loaded", "Cog is not loaded.")
                if operation_type is ApplicationOperationType.COG_UNLOAD:
                    blockers = [
                        other
                        for other in definition.cogs.values()
                        if cog.cog_id in other.dependencies and other.extension in loaded
                    ]
                    if blockers:
                        raise ApplicationOperationError(
                            "cog_dependency_conflict", "Cog is required by a loaded cog."
                        )
                method = {
                    ApplicationOperationType.COG_LOAD: self._adapter.load_cog,
                    ApplicationOperationType.COG_UNLOAD: self._adapter.unload_cog,
                    ApplicationOperationType.COG_RELOAD: self._adapter.reload_cog,
                }[operation_type]
                await method(bot_id, operation.process_instance_id, cog.extension)
                await self._verify_instance(bot_id, operation.process_instance_id)
                operation.status = ApplicationOperationStatus.SUCCEEDED
                operation.result_summary = (
                    f"{cog.display_name}: {operation_type.value.split('.')[-1]} succeeded"
                )
            except ApplicationOperationError as exc:
                self._fail(actor, operation, exc.code)
                raise
            except Exception:
                self._fail(actor, operation, "cog_operation_failed")
                raise ApplicationOperationError(
                    "cog_operation_failed", "Cog operation failed.", 502
                ) from None
        self._complete(actor, operation)
        return operation

    async def _set_maintenance(self, actor, bot_id, request_id, enabled):
        capability = Capability.MAINTENANCE_ENABLE if enabled else Capability.MAINTENANCE_DISABLE
        operation_type = (
            ApplicationOperationType.MAINTENANCE_ENABLE
            if enabled
            else ApplicationOperationType.MAINTENANCE_DISABLE
        )
        self._authorize(actor, bot_id, capability, "maintenance.manage")
        operation = await self._begin(actor, bot_id, request_id, operation_type)
        async with self._lock(bot_id, operation):
            try:
                await self._adapter.set_maintenance(bot_id, operation.process_instance_id, enabled)
                await self._verify_instance(bot_id, operation.process_instance_id)
                operation.status = ApplicationOperationStatus.SUCCEEDED
                operation.result_summary = (
                    "Maintenance enabled" if enabled else "Maintenance disabled"
                )
            except ApplicationOperationError:
                raise
            except Exception:
                self._fail(actor, operation, "management_channel_unavailable")
                raise self._transport_error() from None
        self._complete(actor, operation)
        return operation

    def _definition(self, bot_id):
        if len(bot_id) > 64 or bot_id not in self._catalog:
            raise ApplicationOperationError("unknown_bot", "Bot is not registered.", 404)
        try:
            self._supervisor.get_bot(bot_id)
        except Exception:
            raise ApplicationOperationError("unknown_bot", "Bot is not registered.", 404) from None
        return self._catalog[bot_id]

    def _authorize(self, actor, bot_id, capability, permission):
        definition = self._definition(bot_id)
        # Do authorization before disclosing capability/catalog details.
        if not self._authorizer.can(actor, permission, bot_id=bot_id):
            raise ApplicationOperationError("permission_denied", "Permission is denied.", 403)
        if capability not in definition.capabilities:
            raise ApplicationOperationError(
                "capability_not_supported", "Capability is not supported."
            )
        return definition

    def _resolve_cog(self, definition, cog_id):
        if len(cog_id) > MAX_COG_ID_LENGTH or not COG_ID_PATTERN.fullmatch(cog_id):
            raise ApplicationOperationError("cog_not_found", "Cog was not found.", 404)
        cog = definition.cogs.get(cog_id)
        if cog is None:
            raise ApplicationOperationError("cog_not_found", "Cog was not found.", 404)
        return cog

    async def _prerequisites(self, bot_id, *, ready):
        state = self._supervisor.get_process_state(bot_id)
        if state is not ProcessState.RUNNING:
            code = (
                "lifecycle_operation_in_progress"
                if state in {ProcessState.STARTING, ProcessState.STOPPING, ProcessState.RESTARTING}
                else "bot_not_running"
            )
            raise ApplicationOperationError(code, "Bot is not available for this operation.")
        snapshot = await self._health.get(bot_id)
        evidence = snapshot.evidence if snapshot else None
        if (
            not snapshot
            or not evidence.process_running
            or not evidence.identity_verified
            or not evidence.process_instance_id
        ):
            raise ApplicationOperationError("bot_not_ready", "Bot is not ready.")
        if ready and (
            not snapshot.heartbeat_fresh
            or not evidence.heartbeat
            or not evidence.heartbeat.discord_ready
        ):
            raise ApplicationOperationError("bot_not_ready", "Bot is not ready.")
        record = self._supervisor.get_process(bot_id)
        if record is None or record.process_instance_id != evidence.process_instance_id:
            raise ApplicationOperationError(
                "process_instance_changed", "Bot process instance changed."
            )
        return evidence.process_instance_id

    async def _begin(self, actor, bot_id, request_id, operation_type, *, cog_id=None, ready=False):
        instance = await self._prerequisites(bot_id, ready=ready)
        operation = ApplicationOperation(
            str(uuid.uuid4()),
            request_id,
            bot_id,
            instance,
            operation_type,
            datetime.now(timezone.utc),
            cog_id=cog_id,
        )
        self._operations[operation.operation_id] = operation
        self._history.append(operation.operation_id)
        self._emit(f"bot.{operation_type.value}.requested", actor, operation, "requested")
        return operation

    def _lock(self, bot_id, operation):
        lock = self._locks[bot_id]
        if lock.locked():
            self._fail(None, operation, "operation_in_progress")
            raise ApplicationOperationError(
                "operation_in_progress", "An application operation is in progress."
            )
        operation.status, operation.started_at = (
            ApplicationOperationStatus.RUNNING,
            datetime.now(timezone.utc),
        )
        return lock

    async def _verify_instance(self, bot_id, expected):
        record = self._supervisor.get_process(bot_id)
        if (
            record is None
            or record.process_instance_id != expected
            or self._supervisor.get_process_state(bot_id) is not ProcessState.RUNNING
        ):
            raise ApplicationOperationError(
                "process_instance_changed", "Bot process instance changed."
            )

    def _complete(self, actor, operation):
        operation.completed_at = datetime.now(timezone.utc)
        self._emit(
            f"bot.{operation.operation_type.value}.completed",
            actor,
            operation,
            operation.status.value,
        )

    def _fail(self, actor, operation, code):
        operation.status, operation.error_code = ApplicationOperationStatus.FAILED, code
        operation.completed_at = datetime.now(timezone.utc)
        self._emit(f"bot.{operation.operation_type.value}.failed", actor, operation, code)

    def _emit(self, name, actor, operation, result):
        if self._audit_sink and actor is not None:
            self._audit_sink(
                ApplicationAuditEvent(
                    name,
                    datetime.now(timezone.utc),
                    operation.request_id,
                    actor.principal_id,
                    operation.bot_id,
                    operation.operation_id,
                    result,
                    operation.cog_id,
                )
            )

    @staticmethod
    def _permission(capability):
        if capability is Capability.COGS_VIEW:
            return "cogs.view"
        if capability.value.startswith("cogs."):
            return "cogs.manage"
        if capability is Capability.COMMANDS_SYNC:
            return "commands.sync"
        if capability is Capability.MAINTENANCE_VIEW:
            return "maintenance.view"
        return "maintenance.manage"

    @staticmethod
    def _transport_error():
        return ApplicationOperationError(
            "management_channel_unavailable", "Bot management channel is unavailable.", 503
        )


class FakeBotControlAdapter:
    """Deterministic no-Discord adapter for tests and development fixtures."""

    def __init__(self, catalog=TRUSTED_CAPABILITY_CATALOG) -> None:
        self.loaded = {
            bot_id: {c.extension for c in definition.cogs.values()}
            for bot_id, definition in catalog.items()
        }
        self.maintenance = {bot_id: False for bot_id in catalog}
        self.command_counts = {bot_id: 0 for bot_id in catalog}
        self.failures: dict[tuple[str, str], Exception] = {}
        self.calls: list[tuple[str, str, str]] = []

    def _check(self, action, bot_id, instance):
        self.calls.append((action, bot_id, instance))
        failure = self.failures.get((action, bot_id))
        if failure:
            raise failure

    async def list_loaded_cogs(self, bot_id, process_instance_id):
        self._check("list", bot_id, process_instance_id)
        return frozenset(self.loaded[bot_id])

    async def load_cog(self, bot_id, process_instance_id, extension):
        self._check("load", bot_id, process_instance_id)
        self.loaded[bot_id].add(extension)

    async def unload_cog(self, bot_id, process_instance_id, extension):
        self._check("unload", bot_id, process_instance_id)
        self.loaded[bot_id].discard(extension)

    async def reload_cog(self, bot_id, process_instance_id, extension):
        self._check("reload", bot_id, process_instance_id)
        if extension not in self.loaded[bot_id]:
            raise RuntimeError("not loaded")

    async def sync_commands(self, bot_id, process_instance_id):
        self._check("sync", bot_id, process_instance_id)
        return self.command_counts[bot_id]

    async def get_maintenance(self, bot_id, process_instance_id):
        self._check("maintenance.get", bot_id, process_instance_id)
        return self.maintenance[bot_id]

    async def set_maintenance(self, bot_id, process_instance_id, enabled):
        self._check("maintenance.set", bot_id, process_instance_id)
        self.maintenance[bot_id] = enabled
