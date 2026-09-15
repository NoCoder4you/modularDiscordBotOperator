from __future__ import annotations

import re
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

from portal.app import create_app
from portal.identity import SQLiteIdentityStore, hash_password
from portal.management import ApiFailure, BotView, DenyByDefaultAuthorizer, HealthView, LifecycleView, OperationView
from portal.sessions import MemorySessionStore
from portal.web import PortalDependencies

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class BrowserResponse:
    def __init__(self, status, headers, body):
        self.status_code, self.headers, self.text = status, headers, body.decode()


class BrowserClient:
    def __init__(self, app):
        self.app, self.cookies = app, {}

    def get(self, path, **kwargs): return self.request("GET", path, **kwargs)
    def post(self, path, data=None, content=None, headers=None, **kwargs):
        body = content if content is not None else urlencode(data or {}).encode()
        headers = {"content-type": "application/x-www-form-urlencoded", **(headers or {})}
        return self.request("POST", path, body=body, headers=headers, **kwargs)

    def request(self, method, path, body=b"", headers=None, follow_redirects=True):
        async def run():
            parts, sent, messages = urlsplit(path), False, []
            merged = dict(headers or {})
            if self.cookies:
                merged["cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            merged["content-length"] = str(len(body))
            async def receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}
            async def send(message): messages.append(message)
            scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http", "path": parts.path, "raw_path": parts.path.encode(), "query_string": parts.query.encode(), "headers": [(k.lower().encode(), v.encode()) for k, v in merged.items()], "client": ("testclient", 1), "server": ("testserver", 80), "root_path": ""}
            await self.app(scope, receive, send)
            start = next(m for m in messages if m["type"] == "http.response.start")
            response_headers = {k.decode(): v.decode() for k, v in start["headers"]}
            payload = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
            return BrowserResponse(start["status"], response_headers, payload)
        response = asyncio.run(run())
        cookie = response.headers.get("set-cookie", "")
        if cookie:
            name, value = cookie.split(";", 1)[0].split("=", 1)
            if value:
                self.cookies[name] = value
            else:
                self.cookies.pop(name, None)
        if follow_redirects and response.status_code in {301, 302, 303, 307, 308}:
            return self.get(response.headers["location"])
        return response


class FakeManagement:
    def __init__(self):
        self.calls = []

    def list_bots(self, actor):
        return [BotView(bot_id=bot, display_name=bot, enabled=True, startup_policy="manual") for bot in ("cda-admin", "unbot") if actor.bot_ids is None or bot in actor.bot_ids]

    async def health(self, actor, bot_id):
        if actor.bot_ids is not None and bot_id not in actor.bot_ids:
            raise ApiFailure(403, "permission_denied", "Permission is denied.")
        return HealthView(bot_id=bot_id, derived_state="crash_loop", process_running=False, heartbeat_fresh=False, discord_connected=False, discord_ready=False, maintenance=False, state_changed_at=NOW, reason="canonical fixture")

    async def lifecycle(self, actor, bot_id, action):
        permission = f"bots.{action}"
        if permission not in actor.permissions or (actor.bot_ids is not None and bot_id not in actor.bot_ids):
            raise ApiFailure(403, "permission_denied", "Permission is denied.")
        self.calls.append((bot_id, action))
        operation = OperationView(operation_id="123e4567-e89b-42d3-a456-426614174000", bot_id=bot_id, action=action, status="running", requested_at=NOW, started_at=NOW, completed_at=None, error_code=None)
        return LifecycleView(operation=operation, previous_state="offline", current_state="starting")

    def operation(self, actor, operation_id):
        if "operations.view" not in actor.permissions:
            raise ApiFailure(403, "permission_denied", "Permission is denied.")
        if operation_id != "123e4567-e89b-42d3-a456-426614174000":
            raise ApiFailure(404, "operation_not_found", "Operation was not found.")
        return OperationView(operation_id=operation_id, bot_id="cda-admin", action="restart", status="succeeded", requested_at=NOW, started_at=NOW, completed_at=NOW, error_code=None)


def make_client(tmp_path, permissions=None, bot_ids=frozenset({"cda-admin", "unbot"}), secure=False):
    identities = SQLiteIdentityStore(tmp_path / "identities.sqlite3")
    identity = identities.create("operator", hash_password("fixture-password-123"), frozenset(permissions or {"bots.view", "bots.restart", "operations.view"}), bot_ids)
    sessions = MemorySessionStore()
    management = FakeManagement()
    audits = []
    deps = PortalDependencies(management, identities, sessions, DenyByDefaultAuthorizer(), audits.append, secure)
    return BrowserClient(create_app(portal_dependencies=deps)), identities, identity, sessions, management, audits


def csrf(response):
    return re.search(r"name=csrf_token value='([^']+)'", response.text).group(1)


def login(client):
    page = client.get("/portal/login")
    old = client.cookies.get("mdbo_portal_session")
    response = client.post("/portal/login", data={"login": "operator", "password": "fixture-password-123", "csrf_token": csrf(page)}, follow_redirects=False)
    return old, response


def test_login_csrf_rotation_cookie_and_authorized_list(tmp_path):
    client, _, _, sessions, _, audits = make_client(tmp_path)
    client.get("/portal/login")
    other = BrowserClient(client.app).get("/portal/login")
    assert client.post("/portal/login", data={"login": "operator", "password": "fixture-password-123", "csrf_token": csrf(other)}).status_code == 403
    old, response = login(client)
    assert response.status_code == 303
    assert sessions.get(old) is None
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    listing = client.get("/portal/bots")
    assert listing.status_code == 200 and "cda-admin" in listing.text and "unbot" in listing.text
    assert listing.headers["cache-control"] == "no-store"
    assert "access-control-allow-origin" not in listing.headers
    assert any(event.name == "portal.login.succeeded" for event in audits)


def test_failed_login_is_generic_and_open_redirect_is_rejected(tmp_path):
    client, *_ = make_client(tmp_path)
    page = client.get("/portal/login?next=https://evil.example/")
    response = client.post("/portal/login", data={"login": "unknown", "password": "wrong-password", "csrf_token": csrf(page), "next": "https://evil.example/"})
    assert response.status_code == 401 and "Login failed" in response.text
    assert "wrong-password" not in response.text and "unknown" not in response.text
    page = client.get("/portal/login")
    response = client.post("/portal/login", data={"login": "operator", "password": "fixture-password-123", "csrf_token": csrf(page), "next": "//evil.example/"}, follow_redirects=False)
    assert response.headers["location"] == "/portal/bots"


def test_csrf_lifecycle_logout_and_get_mutations(tmp_path):
    client, _, _, sessions, management, audits = make_client(tmp_path)
    login(client)
    detail = client.get("/portal/bots/cda-admin")
    token = csrf(detail)
    assert client.post("/portal/bots/cda-admin/restart", data={}).status_code == 403
    assert client.post("/portal/bots/cda-admin/restart", data={"csrf_token": "wrong"}).status_code == 403
    accepted = client.post("/portal/bots/cda-admin/restart", data={"csrf_token": token}, follow_redirects=False)
    assert accepted.status_code == 303 and accepted.headers["location"].endswith("123e4567-e89b-42d3-a456-426614174000")
    assert management.calls == [("cda-admin", "restart")]
    assert client.get("/portal/bots/cda-admin/restart").status_code == 405
    session_id = client.cookies.get("mdbo_portal_session")
    assert client.post("/portal/logout", data={"csrf_token": token}, follow_redirects=False).status_code == 303
    assert sessions.get(session_id) is None
    assert any(event.name == "portal.logout" for event in audits)


def test_permissions_are_fresh_and_disabled_identity_loses_session(tmp_path):
    client, identities, identity, sessions, management, _ = make_client(tmp_path)
    login(client)
    page = client.get("/portal/bots/cda-admin")
    assert "Restart" in page.text
    # A current store update is reflected without changing the browser session.
    with identities._connect() as db:
        db.execute("UPDATE portal_identities SET permissions='[\"bots.view\"]' WHERE identity_id=?", (identity.identity_id,))
    page = client.get("/portal/bots/cda-admin")
    assert "Restart" not in page.text
    session = client.cookies.get("mdbo_portal_session")
    csrf_token = sessions.get(session).csrf_token
    assert client.post(
        "/portal/bots/cda-admin/restart", data={"csrf_token": csrf_token}
    ).status_code == 403
    assert management.calls == []
    identities.set_enabled(identity.identity_id, False)
    assert client.get("/portal/bots").status_code == 401


def test_canonical_health_operation_redaction_headers_and_size(tmp_path):
    client, *_ = make_client(tmp_path)
    login(client)
    detail = client.get("/portal/bots/cda-admin")
    assert "crash_loop" in detail.text and "canonical fixture" not in detail.text
    operation = client.get("/portal/operations/123e4567-e89b-42d3-a456-426614174000")
    assert "succeeded" in operation.text and "x-request-id" in operation.headers
    assert operation.headers["x-frame-options"] == "DENY"
    oversized = client.post("/portal/logout", content=b"x" * 5000, headers={"content-type": "application/x-www-form-urlencoded"})
    assert oversized.status_code == 413


def test_secure_cookie_production_setting(tmp_path):
    client, *_ = make_client(tmp_path, secure=True)
    assert "secure" in client.get("/portal/login").headers["set-cookie"].lower()
