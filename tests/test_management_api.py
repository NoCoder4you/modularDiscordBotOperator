from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from portal.app import create_app
from portal.management import (
    DenyByDefaultAuthorizer,
    ManagementDependencies,
    Principal,
    StaticTokenAuthenticator,
)
from supervisor.errors import ProcessStartError, UnknownBotError
from supervisor.health import CanonicalState, DesiredState, HealthEvidence, HealthSnapshot
from supervisor.models import (
    LifecycleAction,
    LifecycleResult,
    OperationRecord,
    OperationStatus,
    ProcessState,
    RegisteredBot,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
TOKEN = "deterministic-management-test-token"
ALL = frozenset({"bots.view", "bots.start", "bots.stop", "bots.restart", "operations.view"})


class Response:
    def __init__(self, status_code, headers, body):
        self.status_code = status_code
        self.headers = headers
        self.text = body.decode()

    def json(self):
        return json.loads(self.text)


class AsgiClient:
    """Dependency-free synchronous ASGI test client."""

    def __init__(self, app):
        self.app = app

    def get(self, path, headers=None): return self.request("GET", path, headers)
    def post(self, path, headers=None): return self.request("POST", path, headers)

    def request(self, method, path, headers=None):
        async def run():
            parts = urlsplit(path)
            sent = False
            messages = []

            async def receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                return {"type": "http.disconnect"}

            async def send(message): messages.append(message)
            scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http", "path": parts.path, "raw_path": quote(parts.path).encode(), "query_string": parts.query.encode(), "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()], "client": ("testclient", 1), "server": ("localhost", 80), "root_path": ""}
            await self.app(scope, receive, send)
            start = next(message for message in messages if message["type"] == "http.response.start")
            body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
            response_headers = {key.decode(): value.decode() for key, value in start["headers"]}
            return Response(start["status"], response_headers, body)
        return asyncio.run(run())


def registered(bot_id: str) -> RegisteredBot:
    return RegisteredBot(bot_id, bot_id.title(), True, "manual", "private.module", Path("/secret/python"), Path("/secret/work"), Path("/secret/runtime"), "DISCORD_TOKEN", 30)


class FakeHealth:
    timing = object()

    def __init__(self) -> None:
        evidence = HealthEvidence("cda-admin", True, DesiredState.RUNNING, True, True, "instance", 1)
        self.snapshot = HealthSnapshot(evidence, CanonicalState.ONLINE, NOW, "canonical-test", True)

    async def get(self, bot_id: str, *, refresh: bool = True) -> HealthSnapshot | None:
        assert refresh
        return self.snapshot if bot_id == "cda-admin" else None


class FakeSupervisor:
    def __init__(self) -> None:
        self.bots = tuple(registered(bot_id) for bot_id in ("cda-admin", "cda-pay", "rpa-admin", "unbot"))
        self.calls: list[tuple[str, str, str | None]] = []
        self.operations: dict[str, OperationRecord] = {}
        self.failure: Exception | None = None

    def list_bots(self):
        return self.bots

    def get_bot(self, bot_id: str):
        for bot in self.bots:
            if bot.bot_id == bot_id:
                return bot
        raise UnknownBotError("unsafe internal detail /etc/passwd")

    def get_operation(self, operation_id: str):
        return self.operations.get(operation_id)

    async def _action(self, action: str, bot_id: str, actor: str | None):
        self.calls.append((action, bot_id, actor))
        if self.failure:
            raise self.failure
        operation = OperationRecord("123e4567-e89b-42d3-a456-426614174000", bot_id, LifecycleAction(action), NOW, OperationStatus.SUCCEEDED, NOW, NOW)
        self.operations[operation.operation_id] = operation
        return LifecycleResult(operation, ProcessState.OFFLINE, ProcessState.RUNNING, "private-instance")

    async def start(self, bot_id: str, *, actor=None): return await self._action("start", bot_id, actor)
    async def stop(self, bot_id: str, *, actor=None): return await self._action("stop", bot_id, actor)
    async def restart(self, bot_id: str, *, actor=None): return await self._action("restart", bot_id, actor)


def client(permissions=ALL, bot_ids=None):
    supervisor = FakeSupervisor()
    principal = Principal("operator-1", frozenset(permissions), None if bot_ids is None else frozenset(bot_ids))
    dependencies = ManagementDependencies(supervisor, FakeHealth(), StaticTokenAuthenticator({TOKEN: principal}), DenyByDefaultAuthorizer())
    return AsgiClient(create_app(dependencies)), supervisor


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_authentication_and_safe_catalog():
    api, _ = client()
    assert api.get("/api/management/v1/bots").status_code == 401
    invalid = api.get("/api/management/v1/bots", headers=auth("wrong"))
    assert invalid.status_code == 401
    response = api.get("/api/management/v1/bots", headers=auth())
    assert response.status_code == 200
    assert {item["bot_id"] for item in response.json()} == {"cda-admin", "cda-pay", "unbot", "rpa-admin"}
    body = response.text
    assert TOKEN not in body and "/secret" not in body and "DISCORD_TOKEN" not in body
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]
    try:
        StaticTokenAuthenticator.from_environment(Principal("x", ALL), environment={})
    except RuntimeError as exc:
        assert "MDBO_MANAGEMENT_TOKEN" in str(exc)
    else:
        raise AssertionError("missing production credential did not fail closed")


def test_authorization_is_deny_default_and_per_bot():
    denied, supervisor = client(set())
    assert denied.post("/api/management/v1/bots/cda-admin/start", headers=auth()).status_code == 403
    assert supervisor.calls == []
    scoped, _ = client(ALL, {"cda-pay"})
    assert scoped.get("/api/management/v1/bots", headers=auth()).json()[0]["bot_id"] == "cda-pay"
    assert scoped.get("/api/management/v1/bots/cda-admin/health", headers=auth()).status_code == 403
    actor = Principal("x", frozenset({"unknown.permission"}))
    assert not DenyByDefaultAuthorizer().can(actor, "unknown.permission")


def test_health_is_serialized_from_canonical_snapshot():
    api, _ = client()
    response = api.get("/api/management/v1/bots/cda-admin/health", headers=auth())
    assert response.status_code == 200
    assert response.json()["derived_state"] == "online"
    assert response.json()["reason"] == "canonical-test"
    assert response.json()["heartbeat_fresh"] is True


def test_lifecycle_and_operation_status_delegate_to_supervisor():
    api, supervisor = client()
    for action in ("start", "stop", "restart"):
        response = api.post(f"/api/management/v1/bots/cda-admin/{action}", headers=auth())
        assert response.status_code == 200
        assert response.json()["operation"]["operation_id"]
    assert [call[0] for call in supervisor.calls] == ["start", "stop", "restart"]
    operation_id = next(iter(supervisor.operations))
    response = api.get(f"/api/management/v1/operations/{operation_id}", headers=auth())
    assert response.json()["status"] == "succeeded"


def test_malicious_ids_never_reach_supervisor():
    api, supervisor = client()
    for value in ("..", "cda-admin.service", "ssh.service", '"; shutdown -h now', "a" * 1000):
        response = api.post(f"/api/management/v1/bots/{value}/restart", headers=auth())
        assert response.status_code in {404, 405}
    assert supervisor.calls == []


def test_failure_is_bounded_and_redacted():
    api, supervisor = client()
    supervisor.failure = ProcessStartError(f"{TOKEN} DISCORD_TOKEN /etc/passwd ['/bin/bash'] bot.service")
    response = api.post("/api/management/v1/bots/cda-admin/start", headers=auth())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "lifecycle_failed"
    assert TOKEN not in response.text and "/etc" not in response.text and "service" not in response.text


def test_unknown_and_malformed_operations_are_bounded():
    api, _ = client()
    for operation_id in ("not-an-id", "123e4567-e89b-42d3-a456-426614174999"):
        response = api.get(f"/api/management/v1/operations/{operation_id}", headers=auth())
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "operation_not_found"
