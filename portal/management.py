"""Authenticated, typed adapter over the authoritative supervisor and health store."""

from __future__ import annotations

import hmac
import logging
import os
import re
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol, TYPE_CHECKING

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from supervisor.errors import SupervisorError, UnknownBotError
from supervisor.health import HealthSnapshot
from supervisor.models import LifecycleResult, OperationRecord, RegisteredBot
from .bot_operations import (
    ApplicationOperation,
    ApplicationOperationError,
    BotOperationService,
    CogStatus,
)

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from .resources import ResourceService
BOT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
OPERATION_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
MAX_REQUEST_BYTES = 4096


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: str
    permissions: frozenset[str]
    bot_ids: frozenset[str] | None = None


class Authenticator(Protocol):
    def authenticate(self, credential: str) -> Principal | None: ...


class Authorizer(Protocol):
    def can(
        self,
        actor: Principal,
        permission: str,
        *,
        bot_id: str | None = None,
        resource_id: str | None = None,
    ) -> bool: ...


class ManagementSupervisor(Protocol):
    def list_bots(self) -> tuple[RegisteredBot, ...]: ...
    def get_bot(self, bot_id: str) -> RegisteredBot: ...
    def get_operation(self, operation_id: str) -> OperationRecord | None: ...
    async def start(self, bot_id: str, *, actor: str | None = None) -> LifecycleResult: ...
    async def stop(self, bot_id: str, *, actor: str | None = None) -> LifecycleResult: ...
    async def restart(self, bot_id: str, *, actor: str | None = None) -> LifecycleResult: ...


class HealthReader(Protocol):
    async def get(self, bot_id: str, *, refresh: bool = True) -> HealthSnapshot | None: ...


@dataclass(frozen=True, slots=True)
class ManagementAuditEvent:
    name: str
    timestamp: datetime
    request_id: str
    actor: str | None = None
    action: str | None = None
    bot_id: str | None = None
    operation_id: str | None = None
    result: str | None = None


class StaticTokenAuthenticator:
    """Constant-time, replaceable Stage 9 credential adapter.

    Tokens are injected by deployment code, never read from Discord credential names.
    """

    def __init__(self, credentials: Mapping[str, Principal]) -> None:
        if not credentials or any(not token for token in credentials):
            raise ValueError("at least one non-empty management credential is required")
        self._credentials = tuple(credentials.items())

    def authenticate(self, credential: str) -> Principal | None:
        match = None
        # Compare every configured token to avoid leaking which entry matched.
        for expected, principal in self._credentials:
            if hmac.compare_digest(credential.encode(), expected.encode()):
                match = principal
        return match

    @classmethod
    def from_environment(
        cls,
        principal: Principal,
        *,
        variable: str = "MDBO_MANAGEMENT_TOKEN",
        environment: Mapping[str, str] | None = None,
    ) -> "StaticTokenAuthenticator":
        """Load the dedicated credential, failing closed when it is absent."""
        source = os.environ if environment is None else environment
        token = source.get(variable)
        if not token:
            raise RuntimeError(f"required management credential {variable} is not configured")
        return cls({token: principal})


class DenyByDefaultAuthorizer:
    KNOWN_PERMISSIONS = frozenset(
        {
            "bots.view",
            "bots.start",
            "bots.stop",
            "bots.restart",
            "operations.view",
            "cogs.view",
            "cogs.manage",
            "commands.sync",
            "maintenance.view",
            "maintenance.manage",
            "config.view",
            "config.edit",
            "data.view",
            "backups.view",
            "backups.create",
            "backups.restore",
        }
    )

    def can(
        self,
        actor: Principal,
        permission: str,
        *,
        bot_id: str | None = None,
        resource_id: str | None = None,
    ) -> bool:
        # resource_id is deliberately part of the boundary even though Stage 13's
        # policy store grants its four base permissions at bot scope.  A future
        # authorizer can narrow a grant without changing resource services.
        del resource_id
        return (
            permission in self.KNOWN_PERMISSIONS
            and permission in actor.permissions
            and (bot_id is None or actor.bot_ids is None or bot_id in actor.bot_ids)
        )


class SlidingWindowLimiter:
    """Small in-process limiter appropriate to one local portal process."""

    def __init__(
        self, limit: int, window_seconds: float, monotonic: Callable[[], float] = time.monotonic
    ):
        self.limit = limit
        self.window = window_seconds
        self._clock = monotonic
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self._clock()
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


@dataclass(slots=True)
class ManagementDependencies:
    supervisor: ManagementSupervisor
    health: HealthReader
    authenticator: Authenticator
    authorizer: Authorizer
    audit_sink: Callable[[ManagementAuditEvent], None] | None = None
    bot_operations: BotOperationService | None = None
    resources: "ResourceService | None" = None
    backups: object | None = None
    auth_limiter: SlidingWindowLimiter = field(default_factory=lambda: SlidingWindowLimiter(10, 60))
    mutation_limiter: SlidingWindowLimiter = field(
        default_factory=lambda: SlidingWindowLimiter(20, 60)
    )


class BotView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot_id: str
    display_name: str
    enabled: bool
    startup_policy: str


class HealthView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot_id: str
    derived_state: str
    process_running: bool
    heartbeat_fresh: bool
    discord_connected: bool
    discord_ready: bool
    maintenance: bool
    state_changed_at: datetime
    reason: str


class OperationView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    bot_id: str
    action: str
    status: str
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None


class LifecycleView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: OperationView
    previous_state: str
    current_state: str


class CogView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cog_id: str
    display_name: str
    description: str
    loaded: bool
    loadable: bool
    unloadable: bool
    reloadable: bool
    required: bool


class ApplicationOperationView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    request_id: str
    bot_id: str
    operation_type: str
    status: str
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cog_id: str | None
    result_summary: str | None
    error_code: str | None


class ApiFailure(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


class ManagementApplication:
    """Stage 9 application boundary shared by JSON and browser transports."""

    def __init__(self, dependencies: ManagementDependencies) -> None:
        self._deps = dependencies

    def require(self, actor: Principal, permission: str, bot_id: str | None = None) -> None:
        if not self._deps.authorizer.can(actor, permission, bot_id=bot_id):
            raise ApiFailure(403, "permission_denied", "Permission is denied.")

    def resolve_bot(self, bot_id: str) -> RegisteredBot:
        if len(bot_id) > 64 or not BOT_ID_PATTERN.fullmatch(bot_id):
            raise ApiFailure(404, "unknown_bot", "Bot is not registered.")
        try:
            return self._deps.supervisor.get_bot(bot_id)
        except UnknownBotError:
            raise ApiFailure(404, "unknown_bot", "Bot is not registered.") from None

    def list_bots(self, actor: Principal) -> list[BotView]:
        self.require(actor, "bots.view")
        return [
            bot_view(bot)
            for bot in self._deps.supervisor.list_bots()
            if self._deps.authorizer.can(actor, "bots.view", bot_id=bot.bot_id)
        ]

    async def health(self, actor: Principal, bot_id: str) -> HealthView:
        bot = self.resolve_bot(bot_id)
        self.require(actor, "bots.view", bot.bot_id)
        snapshot = await self._deps.health.get(bot.bot_id)
        if snapshot is None:
            raise ApiFailure(503, "service_unavailable", "Health evidence is unavailable.")
        heartbeat = snapshot.evidence.heartbeat
        return HealthView(
            bot_id=bot.bot_id,
            derived_state=snapshot.state.value,
            process_running=snapshot.evidence.process_running,
            heartbeat_fresh=snapshot.heartbeat_fresh,
            discord_connected=bool(heartbeat and heartbeat.discord_connected),
            discord_ready=bool(heartbeat and heartbeat.discord_ready),
            maintenance=snapshot.evidence.maintenance_confirmed,
            state_changed_at=snapshot.state_changed_at,
            reason=snapshot.reason,
        )

    async def lifecycle(self, actor: Principal, bot_id: str, action: str) -> LifecycleView:
        if action not in {"start", "stop", "restart"}:
            raise ApiFailure(404, "unknown_action", "Lifecycle action was not found.")
        bot = self.resolve_bot(bot_id)
        self.require(actor, f"bots.{action}", bot.bot_id)
        if not self._deps.mutation_limiter.allow(f"{actor.principal_id}:{bot.bot_id}"):
            raise ApiFailure(429, "rate_limited", "Too many lifecycle requests.")
        try:
            result = await getattr(self._deps.supervisor, action)(
                bot.bot_id, actor=actor.principal_id
            )
        except SupervisorError as exc:
            status, code, message = SAFE_SUPERVISOR_ERRORS.get(
                exc.code, (502, "lifecycle_failed", "Lifecycle operation failed.")
            )
            raise ApiFailure(status, code, message) from None
        return lifecycle_view(result)

    def operation(self, actor: Principal, operation_id: str) -> OperationView:
        if len(operation_id) > 64 or not OPERATION_ID_PATTERN.fullmatch(operation_id):
            raise ApiFailure(404, "operation_not_found", "Operation was not found.")
        record = self._deps.supervisor.get_operation(operation_id)
        if record is None:
            raise ApiFailure(404, "operation_not_found", "Operation was not found.")
        self.require(actor, "operations.view", record.bot_id)
        return operation_view(record)

    def capabilities(self, actor: Principal, bot_id: str) -> tuple[str, ...]:
        self.resolve_bot(bot_id)
        operations = self._bot_operations()
        return tuple(
            sorted(capability.value for capability in operations.capabilities(actor, bot_id))
        )

    async def list_cogs(self, actor: Principal, bot_id: str) -> list[CogView]:
        try:
            return [
                cog_view(item) for item in await self._bot_operations().list_cogs(actor, bot_id)
            ]
        except ApplicationOperationError as exc:
            raise application_failure(exc) from None

    async def load_cog(self, actor, bot_id, cog_id, request_id):
        return await self._application_call("load_cog", actor, bot_id, cog_id, request_id)

    async def unload_cog(self, actor, bot_id, cog_id, request_id):
        return await self._application_call("unload_cog", actor, bot_id, cog_id, request_id)

    async def reload_cog(self, actor, bot_id, cog_id, request_id):
        return await self._application_call("reload_cog", actor, bot_id, cog_id, request_id)

    async def reload_all_cogs(self, actor, bot_id, request_id):
        return await self._application_call("reload_all_cogs", actor, bot_id, request_id)

    async def sync_commands(self, actor, bot_id, request_id):
        return await self._application_call("sync_commands", actor, bot_id, request_id)

    async def get_maintenance(self, actor, bot_id):
        try:
            return await self._bot_operations().get_maintenance(actor, bot_id)
        except ApplicationOperationError as exc:
            raise application_failure(exc) from None

    async def enable_maintenance(self, actor, bot_id, request_id):
        return await self._application_call("enable_maintenance", actor, bot_id, request_id)

    async def disable_maintenance(self, actor, bot_id, request_id):
        return await self._application_call("disable_maintenance", actor, bot_id, request_id)

    def application_operation(self, actor, operation_id):
        try:
            return application_operation_view(
                self._bot_operations().get_operation(actor, operation_id)
            )
        except ApplicationOperationError as exc:
            raise application_failure(exc) from None

    def recent_application_operations(self, actor, bot_id, limit=20):
        try:
            return [
                application_operation_view(item)
                for item in self._bot_operations().recent_operations(actor, bot_id, limit)
            ]
        except ApplicationOperationError as exc:
            raise application_failure(exc) from None

    async def _application_call(self, method, actor, bot_id, *args):
        if not self._deps.mutation_limiter.allow(f"application:{actor.principal_id}:{bot_id}"):
            raise ApiFailure(429, "rate_limited", "Too many application operation requests.")
        try:
            # Method is selected by this closed implementation, never from client input.
            implementation = {
                "load_cog": self._bot_operations().load_cog,
                "unload_cog": self._bot_operations().unload_cog,
                "reload_cog": self._bot_operations().reload_cog,
                "reload_all_cogs": self._bot_operations().reload_all_cogs,
                "sync_commands": self._bot_operations().sync_commands,
                "enable_maintenance": self._bot_operations().enable_maintenance,
                "disable_maintenance": self._bot_operations().disable_maintenance,
            }[method]
            return application_operation_view(await implementation(actor, bot_id, *args))
        except ApplicationOperationError as exc:
            raise application_failure(exc) from None

    def _bot_operations(self) -> BotOperationService:
        if self._deps.bot_operations is None:
            raise ApiFailure(
                503, "management_channel_unavailable", "Bot management channel is unavailable."
            )
        return self._deps.bot_operations


SAFE_SUPERVISOR_ERRORS = {
    "unknown_bot": (404, "unknown_bot", "Bot is not registered."),
    "disabled": (409, "bot_disabled", "Bot is disabled."),
    "already_running": (409, "already_running", "Bot is already running."),
    "already_stopped": (409, "already_stopped", "Bot is already stopped."),
    "operation_in_progress": (
        409,
        "operation_in_progress",
        "A lifecycle operation is in progress.",
    ),
    "supervisor_closed": (503, "service_unavailable", "Supervisor is unavailable."),
}


def install_management_api(app: FastAPI, deps: ManagementDependencies) -> None:
    def emit(name: str, request: Request, **values: str | None) -> None:
        if deps.audit_sink:
            deps.audit_sink(
                ManagementAuditEvent(
                    name=name,
                    timestamp=datetime.now(timezone.utc),
                    request_id=request.state.request_id,
                    **values,
                )
            )

    @app.middleware("http")
    async def management_security(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        if request.url.path.startswith("/api/management/"):
            length = request.headers.get("content-length")
            if length:
                try:
                    too_large = int(length) > MAX_REQUEST_BYTES
                except ValueError:
                    too_large = True
                if too_large:
                    response = error_response(
                        request, 413, "invalid_request", "Request is too large."
                    )
                    return response
            if request.method == "POST" and length not in {None, "0"}:
                return error_response(
                    request, 422, "invalid_request", "Lifecycle requests have no body."
                )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    async def principal(
        request: Request, authorization: str | None = Header(default=None)
    ) -> Principal:
        peer = request.client.host if request.client else "local"
        if not authorization or not authorization.startswith("Bearer "):
            if not deps.auth_limiter.allow(peer):
                raise ApiFailure(429, "rate_limited", "Too many authentication attempts.")
            emit("management.auth.failed", request, result="missing")
            raise ApiFailure(401, "authentication_required", "Authentication is required.")
        credential = authorization[7:]
        actor = deps.authenticator.authenticate(credential)
        if actor is None:
            if not deps.auth_limiter.allow(peer):
                raise ApiFailure(429, "rate_limited", "Too many authentication attempts.")
            emit("management.auth.failed", request, result="invalid")
            raise ApiFailure(401, "authentication_required", "Authentication is required.")
        emit("management.auth.succeeded", request, actor=actor.principal_id, result="succeeded")
        return actor

    def require(
        request: Request, actor: Principal, permission: str, bot_id: str | None = None
    ) -> None:
        if not deps.authorizer.can(actor, permission, bot_id=bot_id):
            emit(
                "management.permission_denied",
                request,
                actor=actor.principal_id,
                action=permission,
                bot_id=bot_id,
                result="denied",
            )
            raise ApiFailure(403, "permission_denied", "Permission is denied.")

    def resolve_bot(bot_id: str) -> RegisteredBot:
        if len(bot_id) > 64 or not BOT_ID_PATTERN.fullmatch(bot_id):
            raise ApiFailure(404, "unknown_bot", "Bot is not registered.")
        try:
            return deps.supervisor.get_bot(bot_id)
        except UnknownBotError:
            raise ApiFailure(404, "unknown_bot", "Bot is not registered.") from None

    @app.get("/api/management/v1/bots", response_model=list[BotView])
    async def bots(request: Request, actor: Principal = Depends(principal)) -> list[BotView]:
        require(request, actor, "bots.view")
        return [
            bot_view(bot)
            for bot in deps.supervisor.list_bots()
            if deps.authorizer.can(actor, "bots.view", bot_id=bot.bot_id)
        ]

    @app.get("/api/management/v1/bots/{bot_id}/health", response_model=HealthView)
    async def bot_health(
        bot_id: str, request: Request, actor: Principal = Depends(principal)
    ) -> HealthView:
        bot = resolve_bot(bot_id)
        require(request, actor, "bots.view", bot.bot_id)
        snapshot = await deps.health.get(bot.bot_id)
        if snapshot is None:
            raise ApiFailure(503, "service_unavailable", "Health evidence is unavailable.")
        evidence = snapshot.evidence
        heartbeat = evidence.heartbeat
        return HealthView(
            bot_id=bot.bot_id,
            derived_state=snapshot.state.value,
            process_running=evidence.process_running,
            heartbeat_fresh=snapshot.heartbeat_fresh,
            discord_connected=bool(heartbeat and heartbeat.discord_connected),
            discord_ready=bool(heartbeat and heartbeat.discord_ready),
            maintenance=evidence.maintenance_confirmed,
            state_changed_at=snapshot.state_changed_at,
            reason=snapshot.reason,
        )

    @app.post("/api/management/v1/bots/{bot_id}/{action}", response_model=LifecycleView)
    async def lifecycle(
        bot_id: str,
        action: Literal["start", "stop", "restart"],
        request: Request,
        actor: Principal = Depends(principal),
    ) -> LifecycleView:
        bot = resolve_bot(bot_id)
        permission = f"bots.{action}"
        require(request, actor, permission, bot.bot_id)
        if not deps.mutation_limiter.allow(f"{actor.principal_id}:{bot.bot_id}"):
            raise ApiFailure(429, "rate_limited", "Too many lifecycle requests.")
        try:
            result = await getattr(deps.supervisor, action)(bot.bot_id, actor=actor.principal_id)
        except SupervisorError as exc:
            status, code, message = SAFE_SUPERVISOR_ERRORS.get(
                exc.code, (502, "lifecycle_failed", "Lifecycle operation failed.")
            )
            emit(
                f"bot.{action}.requested",
                request,
                actor=actor.principal_id,
                action=action,
                bot_id=bot.bot_id,
                result=code,
            )
            logger.error(
                "management lifecycle failure request_id=%s code=%s",
                request.state.request_id,
                exc.code,
            )
            raise ApiFailure(status, code, message) from None
        emit(
            f"bot.{action}.requested",
            request,
            actor=actor.principal_id,
            action=action,
            bot_id=bot.bot_id,
            operation_id=result.operation.operation_id,
            result="accepted",
        )
        return lifecycle_view(result)

    @app.get("/api/management/v1/operations/{operation_id}", response_model=OperationView)
    async def operation(
        operation_id: str, request: Request, actor: Principal = Depends(principal)
    ) -> OperationView:
        if len(operation_id) > 64 or not OPERATION_ID_PATTERN.fullmatch(operation_id):
            raise ApiFailure(404, "operation_not_found", "Operation was not found.")
        record = deps.supervisor.get_operation(operation_id)
        if record is None:
            raise ApiFailure(404, "operation_not_found", "Operation was not found.")
        require(request, actor, "operations.view", record.bot_id)
        return operation_view(record)

    application = ManagementApplication(deps)

    @app.get("/api/management/v1/bots/{bot_id}/capabilities", response_model=list[str])
    async def bot_capabilities(bot_id: str, actor: Principal = Depends(principal)) -> list[str]:
        return list(application.capabilities(actor, bot_id))

    @app.get("/api/management/v1/bots/{bot_id}/cogs", response_model=list[CogView])
    async def bot_cogs(bot_id: str, actor: Principal = Depends(principal)) -> list[CogView]:
        return await application.list_cogs(actor, bot_id)

    @app.post(
        "/api/management/v1/bots/{bot_id}/cogs/{cog_id}/load",
        response_model=ApplicationOperationView,
    )
    async def load_cog(
        bot_id: str, cog_id: str, request: Request, actor: Principal = Depends(principal)
    ):
        return await application.load_cog(actor, bot_id, cog_id, request.state.request_id)

    @app.post(
        "/api/management/v1/bots/{bot_id}/cogs/{cog_id}/unload",
        response_model=ApplicationOperationView,
    )
    async def unload_cog(
        bot_id: str, cog_id: str, request: Request, actor: Principal = Depends(principal)
    ):
        return await application.unload_cog(actor, bot_id, cog_id, request.state.request_id)

    @app.post(
        "/api/management/v1/bots/{bot_id}/cogs/{cog_id}/reload",
        response_model=ApplicationOperationView,
    )
    async def reload_cog(
        bot_id: str, cog_id: str, request: Request, actor: Principal = Depends(principal)
    ):
        return await application.reload_cog(actor, bot_id, cog_id, request.state.request_id)

    @app.post(
        "/api/management/v1/bots/{bot_id}/cogs/reload-all", response_model=ApplicationOperationView
    )
    async def reload_all_cogs(bot_id: str, request: Request, actor: Principal = Depends(principal)):
        return await application.reload_all_cogs(actor, bot_id, request.state.request_id)

    @app.post(
        "/api/management/v1/bots/{bot_id}/commands/sync", response_model=ApplicationOperationView
    )
    async def sync_commands(bot_id: str, request: Request, actor: Principal = Depends(principal)):
        return await application.sync_commands(actor, bot_id, request.state.request_id)

    @app.get("/api/management/v1/bots/{bot_id}/maintenance")
    async def maintenance(bot_id: str, actor: Principal = Depends(principal)) -> dict[str, bool]:
        return {"enabled": await application.get_maintenance(actor, bot_id)}

    @app.post(
        "/api/management/v1/bots/{bot_id}/maintenance/enable",
        response_model=ApplicationOperationView,
    )
    async def enable_maintenance(
        bot_id: str, request: Request, actor: Principal = Depends(principal)
    ):
        return await application.enable_maintenance(actor, bot_id, request.state.request_id)

    @app.post(
        "/api/management/v1/bots/{bot_id}/maintenance/disable",
        response_model=ApplicationOperationView,
    )
    async def disable_maintenance(
        bot_id: str, request: Request, actor: Principal = Depends(principal)
    ):
        return await application.disable_maintenance(actor, bot_id, request.state.request_id)

    @app.get(
        "/api/management/v1/application-operations/{operation_id}",
        response_model=ApplicationOperationView,
    )
    async def application_operation(operation_id: str, actor: Principal = Depends(principal)):
        return application.application_operation(actor, operation_id)

    @app.exception_handler(ApiFailure)
    async def api_failure(request: Request, exc: ApiFailure) -> JSONResponse:
        return error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, _exc: RequestValidationError) -> JSONResponse:
        return error_response(request, 422, "invalid_request", "Request is invalid.")

    @app.exception_handler(Exception)
    async def internal_error(request: Request, _exc: Exception) -> JSONResponse:
        # Exception text can contain argv, paths, environment values, or credentials.
        logger.error(
            "management request failed request_id=%s code=internal_error", request.state.request_id
        )
        return error_response(request, 500, "internal_error", "The request could not be completed.")


def bot_view(bot: RegisteredBot) -> BotView:
    return BotView(
        bot_id=bot.bot_id,
        display_name=bot.display_name,
        enabled=bot.enabled,
        startup_policy=bot.startup_policy,
    )


def operation_view(record: OperationRecord) -> OperationView:
    return OperationView(
        operation_id=record.operation_id,
        bot_id=record.bot_id,
        action=record.action.value,
        status=record.status.value,
        requested_at=record.requested_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        error_code=record.error_category,
    )


def lifecycle_view(result: LifecycleResult) -> LifecycleView:
    return LifecycleView(
        operation=operation_view(result.operation),
        previous_state=result.previous_state.value,
        current_state=result.current_state.value,
    )


def cog_view(item: CogStatus) -> CogView:
    return CogView(**{name: getattr(item, name) for name in CogView.model_fields})


def application_operation_view(item: ApplicationOperation) -> ApplicationOperationView:
    return ApplicationOperationView(
        operation_id=item.operation_id,
        request_id=item.request_id,
        bot_id=item.bot_id,
        operation_type=item.operation_type.value,
        status=item.status.value,
        requested_at=item.requested_at,
        started_at=item.started_at,
        completed_at=item.completed_at,
        cog_id=item.cog_id,
        result_summary=item.result_summary,
        error_code=item.error_code,
    )


def application_failure(exc: ApplicationOperationError) -> ApiFailure:
    return ApiFailure(exc.status, exc.code, exc.safe_message)


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        headers={"X-Request-ID": request_id},
    )
