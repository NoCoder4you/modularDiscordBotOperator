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
        content = f"<ul>{listing}</ul><form method=post action=/portal/logout><input type=hidden name=csrf_token value='{html.escape(session.csrf_token)}'><button>Log out</button></form>"
        return HTMLResponse(_page("Authorized bots", content, request.state.request_id))

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
