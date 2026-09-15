"""Minimal same-origin HTML transport over the Stage 9 management application."""

from __future__ import annotations

import hmac
import html
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .identity import IdentityStore, PortalAuthenticator
from .management import (
    ApiFailure,
    Authorizer,
    ManagementApplication,
    ManagementAuditEvent,
    Principal,
    SlidingWindowLimiter,
    error_response,
)
from .sessions import PortalSession, SessionStore
from .resources import FieldType, ResourceError, ResourceService
from .backups import BackupError, BackupService
from .scheduler import (
    ADMINISTRATIVE_TASK_CATALOG,
    Schedule,
    SchedulerError,
    SchedulerService,
)

COOKIE_NAME = "mdbo_portal_session"
MAX_FORM_BYTES = 4096


@dataclass(slots=True)
class PortalDependencies:
    management: ManagementApplication
    identities: IdentityStore
    sessions: SessionStore
    authorizer: Authorizer
    audit_sink: object | None = None
    secure_cookies: bool = True
    resources: ResourceService | None = None
    backups: BackupService | None = None
    scheduler: SchedulerService | None = None
    backup_limiter: SlidingWindowLimiter = field(
        default_factory=lambda: SlidingWindowLimiter(6, 60)
    )
    login_limiter: SlidingWindowLimiter = field(
        default_factory=lambda: SlidingWindowLimiter(10, 60)
    )


def _page(title: str, content: str, request_id: str) -> str:
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>
</head>
<body><header><h1>{html.escape(title)}</h1></header><main>{content}</main>
<footer><small>Request ID: {html.escape(request_id)}</small></footer></body></html>"""


def _safe_next(value: str | None) -> str:
    if not value:
        return "/portal/bots"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
        return "/portal/bots"
    return value if value.startswith("/portal/") else "/portal/bots"


def install_portal(app: FastAPI, deps: PortalDependencies) -> None:
    auth = PortalAuthenticator(deps.identities)

    def emit(name: str, request: Request, **values: str | None) -> None:
        if callable(deps.audit_sink):
            deps.audit_sink(
                ManagementAuditEvent(
                    name, datetime.now(timezone.utc), request.state.request_id, **values
                )
            )

    def set_cookie(response: Response, session: PortalSession) -> None:
        response.set_cookie(
            COOKIE_NAME,
            session.session_id,
            max_age=8 * 60 * 60,
            secure=deps.secure_cookies,
            httponly=True,
            samesite="strict",
            path="/portal",
        )

    def clear_cookie(response: Response) -> None:
        response.delete_cookie(
            COOKIE_NAME,
            secure=deps.secure_cookies,
            httponly=True,
            samesite="strict",
            path="/portal",
        )

    def session_for(request: Request, *, anonymous: bool = False) -> PortalSession | None:
        token = request.cookies.get(COOKIE_NAME)
        session = deps.sessions.get(token) if token else None
        if token and session is None:
            emit("portal.session.expired", request, result="expired")
        if session is None and anonymous:
            session = deps.sessions.create()
        return session

    def actor_for(request: Request) -> tuple[PortalSession, Principal]:
        session = session_for(request)
        if session is None or session.identity_id is None:
            raise ApiFailure(401, "authentication_required", "Authentication is required.")
        identity = deps.identities.find_by_id(session.identity_id)
        if (
            identity is None
            or not identity.enabled
            or session.session_revision != identity.session_revision
        ):
            deps.sessions.invalidate(session.session_id)
            raise ApiFailure(401, "authentication_required", "Authentication is required.")
        # The authoritative identity is read on every request; permissions are never cached.
        return session, identity.principal()

    async def form(request: Request, session: PortalSession) -> dict[str, str]:
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise ApiFailure(403, "csrf_failed", "Request could not be verified.")
        body = await request.body()
        if len(body) > MAX_FORM_BYTES:
            raise ApiFailure(413, "invalid_request", "Request is too large.")
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("application/x-www-form-urlencoded"):
            raise ApiFailure(422, "invalid_request", "Request is invalid.")
        values = {
            key: items[-1]
            for key, items in parse_qs(
                body.decode("utf-8", "replace"), keep_blank_values=True
            ).items()
        }
        supplied = values.get("csrf_token", "")
        if not hmac.compare_digest(supplied.encode(), session.csrf_token.encode()):
            raise ApiFailure(403, "csrf_failed", "Request could not be verified.")
        return values

    @app.middleware("http")
    async def portal_security(request: Request, call_next):
        if not hasattr(request.state, "request_id"):
            request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        )
        if request.url.path.startswith("/portal"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/portal/login", response_class=HTMLResponse)
    async def login_page(request: Request, next: str | None = None):
        session = session_for(request, anonymous=True)
        assert session is not None
        content = f"""<form method=post action=/portal/login><label>Login <input name=login autocomplete=username required></label><br>
<label>Password <input type=password name=password autocomplete=current-password required></label>
<input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><input type=hidden name=next value='{html.escape(_safe_next(next))}'>
<button type=submit>Sign in</button></form>"""
        response = HTMLResponse(_page("Portal login", content, request.state.request_id))
        set_cookie(response, session)
        return response

    @app.post("/portal/login")
    async def login(request: Request):
        session = session_for(request)
        if session is None:
            raise ApiFailure(403, "csrf_failed", "Request could not be verified.")
        values = await form(request, session)
        peer = request.client.host if request.client else "local"
        if not deps.login_limiter.allow(peer):
            raise ApiFailure(429, "rate_limited", "Too many authentication attempts.")
        identity = auth.authenticate(values.get("login", ""), values.get("password", ""))
        if identity is None:
            emit("portal.login.failed", request, result="invalid")
            content = "<p class=error>Login failed.</p><p><a href=/portal/login>Try again</a></p>"
            return HTMLResponse(
                _page("Portal login", content, request.state.request_id), status_code=401
            )
        rotated = deps.sessions.rotate(
            session.session_id, identity.identity_id, identity.session_revision
        )
        emit("portal.login.succeeded", request, actor=identity.identity_id, result="succeeded")
        response = RedirectResponse(_safe_next(values.get("next")), status_code=303)
        set_cookie(response, rotated)
        return response

    @app.post("/portal/logout")
    async def logout(request: Request):
        session, actor = actor_for(request)
        await form(request, session)
        deps.sessions.invalidate(session.session_id)
        emit("portal.logout", request, actor=actor.principal_id, result="succeeded")
        response = RedirectResponse("/portal/login", status_code=303)
        clear_cookie(response)
        return response

    @app.get("/portal/bots", response_class=HTMLResponse)
    async def bots(request: Request):
        session, actor = actor_for(request)
        items = deps.management.list_bots(actor)
        listing = "".join(
            f"<li><a href='/portal/bots/{html.escape(item.bot_id)}'>{html.escape(item.display_name)}</a> — {'enabled' if item.enabled else 'disabled'}</li>"
            for item in items
        )
        scheduler_link = (
            "<p><a href=/portal/scheduler>Scheduler</a></p>"
            if deps.scheduler is not None
            and any(
                deps.authorizer.can(actor, "scheduler.view", bot_id=item.bot_id) for item in items
            )
            else ""
        )
        content = f"<ul>{listing}</ul>{scheduler_link}<form method=post action=/portal/logout><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>Log out</button></form>"
        return HTMLResponse(_page("Authorized bots", content, request.state.request_id))

    def scheduler_service() -> SchedulerService:
        if deps.scheduler is None:
            raise ApiFailure(404, "scheduler_unavailable", "Scheduler is unavailable.")
        return deps.scheduler

    def scheduler_failure(exc: SchedulerError) -> ApiFailure:
        return ApiFailure(exc.status, exc.code, exc.safe_message)

    def schedule_from_form(values: dict[str, str]) -> Schedule:
        kind = values.get("schedule_kind", "")
        weekdays: tuple[int, ...] = ()
        if values.get("weekdays"):
            try:
                weekdays = tuple(int(x) for x in values["weekdays"].split(","))
            except ValueError:
                raise ApiFailure(422, "schedule_invalid", "Schedule is invalid.") from None
        interval = None
        if values.get("interval_seconds"):
            try:
                interval = int(values["interval_seconds"])
            except ValueError:
                raise ApiFailure(422, "schedule_invalid", "Schedule is invalid.") from None
        return Schedule(
            kind,
            values.get("timezone", ""),
            values.get("at") or None,
            values.get("local_time") or None,
            weekdays,
            interval,
        )

    @app.get("/portal/scheduler", response_class=HTMLResponse)
    async def scheduler_list(request: Request):
        session, actor = actor_for(request)
        tasks = scheduler_service().list_tasks(actor)
        rows = "".join(
            f"<li><a href='/portal/scheduler/{html.escape(task.task_id)}'>{html.escape(task.name)}</a> — {html.escape(task.bot_id)} — {html.escape(task.task_type_id)} — {'enabled' if task.enabled else 'disabled'}</li>"
            for task in tasks
        )
        create = ""
        if any(
            deps.authorizer.can(actor, "scheduler.manage", bot_id=bot_id)
            for bot_id in ("cda-admin", "cda-pay", "unbot", "rpa-admin")
        ):
            create = f"""<h2>Create task</h2><form method=post action=/portal/scheduler>
<input name=name maxlength=80 required placeholder='Task name'><input name=bot_id required placeholder='Bot ID'>
<select name=task_type_id>{"".join(f"<option>{html.escape(key)}</option>" for key in ADMINISTRATIVE_TASK_CATALOG)}</select>
<select name=schedule_kind><option>once</option><option>daily</option><option>weekly</option><option>interval</option></select>
<input name=timezone value=UTC required><input name=at placeholder='ISO timestamp'><input name=local_time placeholder='HH:MM'>
<input name=weekdays placeholder='0,1'><input name=interval_seconds type=number min=900><input name=plan_id placeholder='Trusted backup plan'>
<input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>Create</button></form>"""
        return HTMLResponse(
            _page("Scheduler", f"<ul>{rows}</ul>{create}", request.state.request_id)
        )

    @app.post("/portal/scheduler")
    async def scheduler_create(request: Request):
        session, actor = actor_for(request)
        values = await form(request, session)
        params = {"plan_id": values["plan_id"]} if values.get("plan_id") else {}
        try:
            task = scheduler_service().create(
                actor,
                name=values.get("name", ""),
                bot_id=values.get("bot_id", ""),
                task_type_id=values.get("task_type_id", ""),
                schedule=schedule_from_form(values),
                parameters=params,
                request_id=request.state.request_id,
            )
        except SchedulerError as exc:
            raise scheduler_failure(exc) from None
        return RedirectResponse(f"/portal/scheduler/{task.task_id}", status_code=303)

    @app.get("/portal/scheduler/{task_id}", response_class=HTMLResponse)
    async def scheduler_detail(task_id: str, request: Request):
        session, actor = actor_for(request)
        try:
            service = scheduler_service()
            task = service.get_task(actor, task_id)
            history = service.store.history(task.task_id)
        except SchedulerError as exc:
            raise scheduler_failure(exc) from None
        executions = "".join(
            f"<li>{html.escape(item.execution_id)} — {html.escape(item.status.value)} — {html.escape(item.started_at.isoformat())}</li>"
            for item in history
        )
        controls = ""
        kind = ADMINISTRATIVE_TASK_CATALOG[task.task_type_id]
        if deps.authorizer.can(
            actor, "scheduler.manage", bot_id=task.bot_id
        ) and deps.authorizer.can(actor, kind.underlying_permission, bot_id=task.bot_id):
            schedule = task.schedule
            controls += f"""<details><summary>Edit</summary><form method=post action='/portal/scheduler/{task.task_id}/edit'>
<input name=name maxlength=80 value='{html.escape(task.name)}' required><input type=hidden name=revision value={task.revision}>
<input type=hidden name=schedule_kind value='{html.escape(schedule.kind)}'><input name=timezone value='{html.escape(schedule.timezone)}' required>
<input name=at value='{html.escape(schedule.at or "")}'><input name=local_time value='{html.escape(schedule.local_time or "")}'>
<input name=weekdays value='{html.escape(",".join(str(x) for x in schedule.weekdays))}'><input name=interval_seconds type=number min=900 value='{schedule.interval_seconds or ""}'>
<input name=plan_id value='{html.escape(task.parameters.get("plan_id", ""))}'><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>Save</button></form></details>"""
            controls += f"<form method=post action='/portal/scheduler/{task.task_id}/toggle'><input type=hidden name=revision value={task.revision}><input type=hidden name=enabled value={'false' if task.enabled else 'true'}><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>{'Disable' if task.enabled else 'Enable'}</button></form>"
            controls += f"<form method=post action='/portal/scheduler/{task.task_id}/delete'><input type=hidden name=revision value={task.revision}><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>Delete</button></form>"
        if deps.authorizer.can(actor, "scheduler.run", bot_id=task.bot_id) and deps.authorizer.can(
            actor, kind.underlying_permission, bot_id=task.bot_id
        ):
            controls += f"<form method=post action='/portal/scheduler/{task.task_id}/run'><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>Run now</button></form>"
        content = f"<dl><dt>Task ID</dt><dd>{task.task_id}</dd><dt>Bot</dt><dd>{html.escape(task.bot_id)}</dd><dt>Type</dt><dd>{html.escape(task.task_type_id)}</dd><dt>Owner</dt><dd>{html.escape(task.owner_id)}</dd><dt>Timezone</dt><dd>{html.escape(task.schedule.timezone)}</dd><dt>Revision</dt><dd>{task.revision}</dd></dl>{controls}<h2>Recent executions</h2><ul>{executions}</ul>"
        return HTMLResponse(_page(task.name, content, request.state.request_id))

    @app.post("/portal/scheduler/{task_id}/edit")
    async def scheduler_edit(task_id: str, request: Request):
        session, actor = actor_for(request)
        values = await form(request, session)
        params = {"plan_id": values["plan_id"]} if values.get("plan_id") else {}
        try:
            scheduler_service().update(
                actor,
                task_id,
                int(values.get("revision", "-1")),
                name=values.get("name", ""),
                schedule=schedule_from_form(values),
                parameters=params,
                request_id=request.state.request_id,
            )
        except SchedulerError as exc:
            raise scheduler_failure(exc) from None
        except ValueError:
            raise ApiFailure(422, "stale_revision", "Task revision is invalid.") from None
        return RedirectResponse(f"/portal/scheduler/{task_id}", status_code=303)

    @app.post("/portal/scheduler/{task_id}/toggle")
    async def scheduler_toggle(task_id: str, request: Request):
        session, actor = actor_for(request)
        values = await form(request, session)
        try:
            scheduler_service().set_enabled(
                actor,
                task_id,
                int(values.get("revision", "-1")),
                values.get("enabled") == "true",
                request.state.request_id,
            )
        except (SchedulerError, ValueError) as exc:
            if isinstance(exc, SchedulerError):
                raise scheduler_failure(exc) from None
            raise ApiFailure(422, "stale_revision", "Task revision is invalid.") from None
        return RedirectResponse(f"/portal/scheduler/{task_id}", status_code=303)

    @app.post("/portal/scheduler/{task_id}/delete")
    async def scheduler_delete(task_id: str, request: Request):
        session, actor = actor_for(request)
        values = await form(request, session)
        try:
            scheduler_service().delete(
                actor, task_id, int(values.get("revision", "-1")), request.state.request_id
            )
        except SchedulerError as exc:
            raise scheduler_failure(exc) from None
        except ValueError:
            raise ApiFailure(422, "stale_revision", "Task revision is invalid.") from None
        return RedirectResponse("/portal/scheduler", status_code=303)

    @app.post("/portal/scheduler/{task_id}/run")
    async def scheduler_run(task_id: str, request: Request):
        session, actor = actor_for(request)
        await form(request, session)
        try:
            await scheduler_service().run_now(actor, task_id, request.state.request_id)
        except SchedulerError as exc:
            raise scheduler_failure(exc) from None
        return RedirectResponse(f"/portal/scheduler/{task_id}", status_code=303)

    @app.get("/portal/bots/{bot_id}", response_class=HTMLResponse)
    async def bot_detail(bot_id: str, request: Request):
        session, actor = actor_for(request)
        health = await deps.management.health(actor, bot_id)
        capabilities = (
            set(deps.management.capabilities(actor, bot_id))
            if hasattr(deps.management, "capabilities")
            else set()
        )
        controls = "".join(
            f"<form method=post action='/portal/bots/{html.escape(bot_id)}/{action}'><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>{action.title()}</button></form>"
            for action in ("start", "stop", "restart")
            if deps.authorizer.can(actor, f"bots.{action}", bot_id=bot_id)
        )
        sections = []
        if deps.resources is not None:
            configs = deps.resources.list_config(actor, bot_id)
            if configs:
                links = "".join(
                    f"<li><a href='/portal/bots/{html.escape(bot_id)}/config/{html.escape(item.resource_id)}'>{html.escape(item.display_name)}</a></li>"
                    for item in configs
                )
                sections.append(f"<section><h2>Configuration</h2><ul>{links}</ul></section>")
            data_resources = deps.resources.list_data(actor, bot_id)
            if data_resources:
                links = "".join(
                    f"<li><a href='/portal/bots/{html.escape(bot_id)}/data/{html.escape(item.resource_id)}'>{html.escape(item.display_name)}</a></li>"
                    for item in data_resources
                )
                sections.append(f"<section><h2>Data</h2><ul>{links}</ul></section>")
        if deps.backups is not None and deps.authorizer.can(actor, "backups.view", bot_id=bot_id):
            sections.append(
                f"<section><h2>Backups</h2><p><a href='/portal/bots/{html.escape(bot_id)}/backups'>Manage backups</a></p></section>"
            )
        if "cogs.view" in capabilities:
            sections.append(
                f"<section><h2>Cogs</h2><p><a href='/portal/bots/{html.escape(bot_id)}/cogs'>View trusted cog inventory</a></p></section>"
            )
        if "commands.sync" in capabilities and health.process_running and health.discord_ready:
            sections.append(
                f"<section><h2>Commands</h2><form method=post action='/portal/bots/{html.escape(bot_id)}/commands/sync'><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>Synchronize configured commands</button></form></section>"
            )
        if {"maintenance.view", "maintenance.enable", "maintenance.disable"} & capabilities:
            sections.append(
                "<section><h2>Maintenance</h2><p>Maintenance evidence is reported through canonical health.</p></section>"
            )
        if hasattr(deps.management, "recent_application_operations") and deps.authorizer.can(
            actor, "operations.view", bot_id=bot_id
        ):
            recent = deps.management.recent_application_operations(actor, bot_id)
            rows = "".join(
                f"<li><a href='/portal/application-operations/{html.escape(item.operation_id)}'>{html.escape(item.operation_type)}</a> — {html.escape(item.status)}</li>"
                for item in recent
            )
            sections.append(
                f"<section><h2>Recent application operations</h2><ul>{rows}</ul></section>"
            )
        content = f"<section><h2>Overview</h2><dl><dt>Bot ID</dt><dd>{html.escape(bot_id)}</dd><dt>Canonical state</dt><dd>{html.escape(health.derived_state)}</dd><dt>Heartbeat fresh</dt><dd>{health.heartbeat_fresh}</dd><dt>Discord connected</dt><dd>{health.discord_connected}</dd><dt>Discord READY</dt><dd>{health.discord_ready}</dd><dt>Maintenance</dt><dd>{health.maintenance}</dd><dt>State changed</dt><dd>{html.escape(health.state_changed_at.isoformat())}</dd></dl></section><section><h2>Lifecycle</h2>{controls}</section>{''.join(sections)}<p><a href=/portal/bots>Back</a></p>"
        return HTMLResponse(_page("Bot status", content, request.state.request_id))

    @app.get("/portal/bots/{bot_id}/config/{resource_id}", response_class=HTMLResponse)
    async def config_detail(bot_id: str, resource_id: str, request: Request):
        session, actor = actor_for(request)
        if deps.resources is None:
            raise ApiFailure(404, "resource_not_found", "Resource was not found.")
        try:
            resource, snapshot = deps.resources.get_config(
                actor, bot_id, resource_id, request.state.request_id
            )
        except ResourceError as exc:
            raise ApiFailure(exc.status, exc.code, exc.safe_message) from None
        editable = resource.edit_permission is not None and deps.authorizer.can(
            actor, resource.edit_permission, bot_id=bot_id, resource_id=resource_id
        )
        fields = []
        for definition in resource.fields:
            value = snapshot.values.get(definition.field_id, "")
            escaped = html.escape(str(value))
            control = escaped
            if editable and not definition.read_only:
                input_type = "number" if definition.field_type is FieldType.INTEGER else "text"
                control = f"<input type={input_type} name='{html.escape(definition.field_id)}' value='{escaped}' required>"
            fields.append(
                f"<label>{html.escape(definition.label)} {control}</label><small>{html.escape(definition.description)}</small><br>"
            )
        start = (
            f"<form method=post action='/portal/bots/{html.escape(bot_id)}/config/{html.escape(resource_id)}/preview'>"
            if editable
            else ""
        )
        end = (
            f"<input type=hidden name=expected_revision value='{html.escape(snapshot.revision)}'><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>Preview changes</button></form>"
            if editable
            else ""
        )
        return HTMLResponse(
            _page(
                resource.display_name,
                f"<p>Revision: {html.escape(snapshot.revision)}</p>{start}{''.join(fields)}{end}",
                request.state.request_id,
            )
        )

    def config_submission(resource, values):
        submitted = {}
        for definition in resource.fields:
            raw = values.get(definition.field_id)
            if raw is None:
                continue
            if definition.field_type is FieldType.INTEGER:
                try:
                    submitted[definition.field_id] = int(raw)
                except ValueError:
                    submitted[definition.field_id] = raw
            elif definition.field_type is FieldType.BOOLEAN:
                submitted[definition.field_id] = raw == "true"
            else:
                submitted[definition.field_id] = raw
        return submitted

    @app.post("/portal/bots/{bot_id}/config/{resource_id}/preview", response_class=HTMLResponse)
    async def config_preview(bot_id: str, resource_id: str, request: Request):
        session, actor = actor_for(request)
        values = await form(request, session)
        if deps.resources is None:
            raise ApiFailure(404, "resource_not_found", "Resource was not found.")
        try:
            resource, _ = deps.resources.get_config(
                actor, bot_id, resource_id, request.state.request_id
            )
            submitted = config_submission(resource, values)
            preview = deps.resources.preview(
                actor,
                bot_id,
                resource_id,
                submitted,
                values.get("expected_revision", ""),
                request.state.request_id,
            )
        except ResourceError as exc:
            raise ApiFailure(exc.status, exc.code, exc.safe_message) from None
        rows = (
            "".join(
                f"<li>{html.escape(change.field_id)}: {html.escape(str(change.old_value))} → {html.escape(str(change.new_value))}{' (restart required)' if change.restart_required else ''}</li>"
                for change in preview.changes
            )
            or "<li>No changes</li>"
        )
        hidden = "".join(
            f"<input type=hidden name='{html.escape(name)}' value='{html.escape(str(value))}'>"
            for name, value in preview.values.items()
        )
        content = f"<ul>{rows}</ul><form method=post action='/portal/bots/{html.escape(bot_id)}/config/{html.escape(resource_id)}/commit'>{hidden}<input type=hidden name=expected_revision value='{html.escape(preview.expected_revision)}'><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>Confirm</button></form>"
        return HTMLResponse(_page("Confirm configuration", content, request.state.request_id))

    @app.post("/portal/bots/{bot_id}/config/{resource_id}/commit")
    async def config_commit(bot_id: str, resource_id: str, request: Request):
        session, actor = actor_for(request)
        values = await form(request, session)
        if deps.resources is None:
            raise ApiFailure(404, "resource_not_found", "Resource was not found.")
        try:
            resource, _ = deps.resources.get_config(
                actor, bot_id, resource_id, request.state.request_id
            )
            deps.resources.commit(
                actor,
                bot_id,
                resource_id,
                config_submission(resource, values),
                values.get("expected_revision", ""),
                request.state.request_id,
            )
        except ResourceError as exc:
            raise ApiFailure(exc.status, exc.code, exc.safe_message) from None
        return RedirectResponse(f"/portal/bots/{bot_id}/config/{resource_id}", status_code=303)

    @app.get("/portal/bots/{bot_id}/data/{resource_id}", response_class=HTMLResponse)
    async def data_view(
        bot_id: str, resource_id: str, request: Request, limit: int = 25, cursor: str | None = None
    ):
        _, actor = actor_for(request)
        if deps.resources is None:
            raise ApiFailure(404, "resource_not_found", "Resource was not found.")
        try:
            page = deps.resources.data_page(
                actor, bot_id, resource_id, request.state.request_id, limit=limit, cursor=cursor
            )
        except ResourceError as exc:
            raise ApiFailure(exc.status, exc.code, exc.safe_message) from None
        rows = "".join(
            "<li>"
            + " — ".join(html.escape(str(record.get(field, ""))) for field in page.resource.fields)
            + "</li>"
            for record in page.records
        )
        more = (
            f"<a href='?limit={limit}&amp;cursor={html.escape(page.next_cursor)}'>Next</a>"
            if page.next_cursor
            else ""
        )
        return HTMLResponse(
            _page(page.resource.display_name, f"<ul>{rows}</ul>{more}", request.state.request_id)
        )

    @app.get("/portal/bots/{bot_id}/backups", response_class=HTMLResponse)
    async def backup_list(bot_id: str, request: Request):
        session, actor = actor_for(request)
        if deps.backups is None:
            raise ApiFailure(404, "backup_not_found", "Backup was not found.")
        try:
            items = deps.backups.list_backups(actor, bot_id)
            plans = deps.backups.list_backup_plans(actor, bot_id)
        except BackupError as exc:
            raise ApiFailure(exc.status, exc.code, exc.safe_message) from None
        rows = (
            "".join(
                f"<li><a href='/portal/bots/{html.escape(bot_id)}/backups/{html.escape(item.backup_id)}'>{html.escape(item.backup_id)}</a> — {html.escape(item.created_at.isoformat())} — {item.total_bytes} bytes</li>"
                for item in items
            )
            or "<li>No completed backups</li>"
        )
        create = ""
        if deps.authorizer.can(actor, "backups.create", bot_id=bot_id):
            create = "".join(
                f"<form method=post action='/portal/bots/{html.escape(bot_id)}/backups'><input type=hidden name=plan_id value='{html.escape(plan.plan_id)}'><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>Create backup</button></form>"
                for plan in plans
            )
        return HTMLResponse(_page("Backups", f"{create}<ul>{rows}</ul>", request.state.request_id))

    @app.post("/portal/bots/{bot_id}/backups")
    async def backup_create(bot_id: str, request: Request):
        session, actor = actor_for(request)
        values = await form(request, session)
        if deps.backups is None:
            raise ApiFailure(404, "backup_not_found", "Backup was not found.")
        if not deps.backup_limiter.allow(f"{actor.principal_id}:{bot_id}:create"):
            raise ApiFailure(429, "rate_limited", "Too many backup requests.")
        try:
            item = deps.backups.create_backup(
                actor, bot_id, values.get("plan_id", ""), request.state.request_id
            )
        except BackupError as exc:
            raise ApiFailure(exc.status, exc.code, exc.safe_message) from None
        return RedirectResponse(f"/portal/bots/{bot_id}/backups/{item.backup_id}", status_code=303)

    @app.get("/portal/bots/{bot_id}/backups/{backup_id}", response_class=HTMLResponse)
    async def backup_detail(bot_id: str, backup_id: str, request: Request):
        session, actor = actor_for(request)
        if deps.backups is None:
            raise ApiFailure(404, "backup_not_found", "Backup was not found.")
        try:
            item = deps.backups.get_backup(actor, bot_id, backup_id)
        except BackupError as exc:
            raise ApiFailure(exc.status, exc.code, exc.safe_message) from None
        resources = "".join(
            f"<li>{html.escape(entry.resource_id)} — schema {entry.schema_version} — {entry.size} bytes</li>"
            for entry in item.resources
        )
        restore = ""
        if deps.authorizer.can(actor, "backups.restore", bot_id=bot_id):
            restore = f"<form method=post action='/portal/bots/{html.escape(bot_id)}/backups/{html.escape(backup_id)}/preview'><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>Preview restore</button></form>"
        content = f"<dl><dt>Backup ID</dt><dd>{html.escape(item.backup_id)}</dd><dt>Plan</dt><dd>{html.escape(item.plan_id)}</dd><dt>Format</dt><dd>{item.format_version}</dd><dt>Integrity</dt><dd>{html.escape(item.integrity_status)}</dd><dt>Status</dt><dd>{html.escape(item.status)}</dd></dl><ul>{resources}</ul>{restore}"
        return HTMLResponse(_page("Backup detail", content, request.state.request_id))

    @app.post("/portal/bots/{bot_id}/backups/{backup_id}/preview", response_class=HTMLResponse)
    async def restore_preview(bot_id: str, backup_id: str, request: Request):
        session, actor = actor_for(request)
        await form(request, session)
        if deps.backups is None:
            raise ApiFailure(404, "backup_not_found", "Backup was not found.")
        try:
            preview = deps.backups.preview_restore(
                actor, bot_id, backup_id, request.state.request_id
            )
        except BackupError as exc:
            raise ApiFailure(exc.status, exc.code, exc.safe_message) from None
        rows = "".join(
            f"<li>{html.escape(change.resource_id)} — {html.escape(change.summary)} — current {html.escape(change.current_revision)} / backup {html.escape(change.backup_revision)}{' — restart required' if change.restart_required else ''}</li>"
            for change in preview.changes
        )
        content = f"<p>Compatibility: compatible</p><ul>{rows}</ul><form method=post action='/portal/bots/{html.escape(bot_id)}/backups/{html.escape(backup_id)}/restore'><input type=hidden name=preview_id value='{html.escape(preview.preview_id)}'><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>Confirm restore</button></form>"
        return HTMLResponse(_page("Confirm restore", content, request.state.request_id))

    @app.post("/portal/bots/{bot_id}/backups/{backup_id}/restore")
    async def restore_commit(bot_id: str, backup_id: str, request: Request):
        session, actor = actor_for(request)
        values = await form(request, session)
        if deps.backups is None:
            raise ApiFailure(404, "backup_not_found", "Backup was not found.")
        if not deps.backup_limiter.allow(f"{actor.principal_id}:{bot_id}:restore"):
            raise ApiFailure(429, "rate_limited", "Too many restore requests.")
        try:
            deps.backups.restore_backup(
                actor, bot_id, backup_id, values.get("preview_id", ""), request.state.request_id
            )
        except BackupError as exc:
            raise ApiFailure(exc.status, exc.code, exc.safe_message) from None
        return RedirectResponse(f"/portal/bots/{bot_id}/backups/{backup_id}", status_code=303)

    @app.get("/portal/bots/{bot_id}/cogs", response_class=HTMLResponse)
    async def cogs(bot_id: str, request: Request):
        session, actor = actor_for(request)
        items = await deps.management.list_cogs(actor, bot_id)
        can_manage = deps.authorizer.can(actor, "cogs.manage", bot_id=bot_id)
        rows = []
        for item in items:
            buttons = []
            for action, allowed in (
                ("load", item.loadable and not item.loaded),
                ("unload", item.unloadable and item.loaded),
                ("reload", item.reloadable and item.loaded),
            ):
                if can_manage and allowed:
                    buttons.append(
                        f"<form method=post action='/portal/bots/{html.escape(bot_id)}/cogs/{html.escape(item.cog_id)}/{action}'><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>{action.title()}</button></form>"
                    )
            rows.append(
                f"<li><strong>{html.escape(item.display_name)}</strong> — {'loaded' if item.loaded else 'unloaded'}{' — required' if item.required else ''}{''.join(buttons)}</li>"
            )
        return HTMLResponse(
            _page(
                "Trusted cogs",
                f"<ul>{''.join(rows)}</ul><p><a href='/portal/bots/{html.escape(bot_id)}'>Back</a></p>",
                request.state.request_id,
            )
        )

    @app.post("/portal/bots/{bot_id}/cogs/{cog_id}/{action}")
    async def cog_mutation(bot_id: str, cog_id: str, action: str, request: Request):
        session, actor = actor_for(request)
        await form(request, session)
        methods = {
            "load": deps.management.load_cog,
            "unload": deps.management.unload_cog,
            "reload": deps.management.reload_cog,
        }
        if action not in methods:
            raise ApiFailure(404, "unknown_action", "Cog action was not found.")
        item = await methods[action](actor, bot_id, cog_id, request.state.request_id)
        return RedirectResponse(
            f"/portal/application-operations/{item.operation_id}", status_code=303
        )

    @app.post("/portal/bots/{bot_id}/commands/sync")
    async def command_sync(bot_id: str, request: Request):
        session, actor = actor_for(request)
        await form(request, session)
        item = await deps.management.sync_commands(actor, bot_id, request.state.request_id)
        return RedirectResponse(
            f"/portal/application-operations/{item.operation_id}", status_code=303
        )

    @app.post("/portal/bots/{bot_id}/maintenance/{action}")
    async def maintenance_mutation(bot_id: str, action: str, request: Request):
        session, actor = actor_for(request)
        await form(request, session)
        methods = {
            "enable": deps.management.enable_maintenance,
            "disable": deps.management.disable_maintenance,
        }
        if action not in methods:
            raise ApiFailure(404, "unknown_action", "Maintenance action was not found.")
        item = await methods[action](actor, bot_id, request.state.request_id)
        return RedirectResponse(
            f"/portal/application-operations/{item.operation_id}", status_code=303
        )

    @app.post("/portal/bots/{bot_id}/{action}")
    async def lifecycle(bot_id: str, action: str, request: Request):
        session, actor = actor_for(request)
        await form(request, session)
        try:
            result = await deps.management.lifecycle(actor, bot_id, action)
        except ApiFailure as exc:
            emit("portal.lifecycle.rejected", request, actor=actor.principal_id, result=exc.code)
            raise
        emit(
            f"bot.{action}.requested",
            request,
            actor=actor.principal_id,
            action=action,
            bot_id=bot_id,
            operation_id=result.operation.operation_id,
            result="accepted",
        )
        return RedirectResponse(
            f"/portal/operations/{result.operation.operation_id}", status_code=303
        )

    @app.get("/portal/operations/{operation_id}", response_class=HTMLResponse)
    async def operation(operation_id: str, request: Request):
        _, actor = actor_for(request)
        item = deps.management.operation(actor, operation_id)
        content = f"<dl><dt>Operation ID</dt><dd>{html.escape(item.operation_id)}</dd><dt>Bot</dt><dd>{html.escape(item.bot_id)}</dd><dt>Action</dt><dd>{html.escape(item.action)}</dd><dt>Status</dt><dd>{html.escape(item.status)}</dd><dt>Requested</dt><dd>{html.escape(item.requested_at.isoformat())}</dd></dl><p><a href='/portal/bots/{html.escape(item.bot_id)}'>Bot status</a></p>"
        return HTMLResponse(_page("Operation status", content, request.state.request_id))

    @app.get("/portal/application-operations/{operation_id}", response_class=HTMLResponse)
    async def application_operation(operation_id: str, request: Request):
        _, actor = actor_for(request)
        item = deps.management.application_operation(actor, operation_id)
        summary = html.escape(item.result_summary or item.error_code or "Pending")
        content = f"<dl><dt>Operation ID</dt><dd>{html.escape(item.operation_id)}</dd><dt>Bot</dt><dd>{html.escape(item.bot_id)}</dd><dt>Type</dt><dd>{html.escape(item.operation_type)}</dd><dt>Status</dt><dd>{html.escape(item.status)}</dd><dt>Requested</dt><dd>{html.escape(item.requested_at.isoformat())}</dd><dt>Result</dt><dd>{summary}</dd></dl><p><a href='/portal/bots/{html.escape(item.bot_id)}'>Bot status</a></p>"
        return HTMLResponse(_page("Application operation", content, request.state.request_id))

    @app.exception_handler(ApiFailure)
    async def portal_failure(request: Request, exc: ApiFailure):
        if request.url.path.startswith("/portal"):
            content = f"<p class=error>{html.escape(exc.message)}</p>"
            response = HTMLResponse(
                _page("Request failed", content, request.state.request_id), status_code=exc.status
            )
            if exc.status == 401:
                clear_cookie(response)
            return response
        # The Stage 9 handler remains authoritative for management API failures.
        return error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(Exception)
    async def unexpected_failure(request: Request, _exc: Exception):
        if request.url.path.startswith("/portal"):
            content = "<p class=error>The request could not be completed.</p>"
            return HTMLResponse(
                _page("Request failed", content, request.state.request_id), status_code=500
            )
        return error_response(request, 500, "internal_error", "The request could not be completed.")
