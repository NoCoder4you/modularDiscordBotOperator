from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from portal.bot_operations import (
    ApplicationOperationError,
    BotOperationService,
    Capability,
    FakeBotControlAdapter,
    TRUSTED_CAPABILITY_CATALOG,
)
from portal.management import DenyByDefaultAuthorizer, Principal
from shared.heartbeat import Heartbeat
from supervisor.health import CanonicalState, DesiredState, HealthEvidence, HealthSnapshot
from supervisor.models import ProcessState

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
PERMISSIONS = frozenset({"cogs.view", "cogs.manage", "commands.sync", "operations.view"})


class Supervisor:
    def __init__(self):
        self.state = ProcessState.RUNNING
        self.instance = "instance-a"

    def get_bot(self, bot_id):
        if bot_id not in TRUSTED_CAPABILITY_CATALOG:
            raise KeyError(bot_id)
        return SimpleNamespace(bot_id=bot_id)

    def get_process_state(self, bot_id):
        self.get_bot(bot_id)
        return self.state

    def get_process(self, bot_id):
        self.get_bot(bot_id)
        return SimpleNamespace(process_instance_id=self.instance)


class Health:
    def __init__(self, supervisor):
        self.supervisor = supervisor
        self.ready = True

    async def get(self, bot_id, *, refresh=True):
        heartbeat = Heartbeat(1, bot_id, self.supervisor.instance, 1, NOW, True, self.ready, False)
        evidence = HealthEvidence(
            bot_id,
            True,
            DesiredState.RUNNING,
            True,
            True,
            self.supervisor.instance,
            1,
            heartbeat,
            1,
        )
        return HealthSnapshot(evidence, CanonicalState.ONLINE, NOW, "test", True)


def fixture_service(*, permissions=PERMISSIONS, bot_ids=None):
    supervisor = Supervisor()
    adapter = FakeBotControlAdapter()
    actor = Principal("operator", permissions, bot_ids)
    audits = []
    service = BotOperationService(
        supervisor,
        Health(supervisor),
        DenyByDefaultAuthorizer(),
        adapter,
        audit_sink=audits.append,
    )
    return service, supervisor, adapter, actor, audits


def run(coro):
    return asyncio.run(coro)


def test_capabilities_are_closed_typed_and_authorized_per_bot():
    service, _, _, actor, _ = fixture_service(bot_ids=frozenset({"cda-admin"}))
    capabilities = service.capabilities(actor, "cda-admin")
    assert Capability.COGS_VIEW in capabilities
    assert Capability.COMMANDS_SYNC in capabilities
    assert Capability.MAINTENANCE_ENABLE not in capabilities
    assert all(isinstance(item, Capability) for item in capabilities)
    # Capability discovery itself does not bypass the per-bot assignment: nothing is visible.
    assert not service.capabilities(actor, "unbot")


def test_cog_list_projects_safe_catalog_and_never_internal_extensions():
    service, _, _, actor, _ = fixture_service()
    items = run(service.list_cogs(actor, "cda-admin"))
    assert items and all(item.loaded for item in items)
    protected = {item.cog_id for item in items if item.required}
    assert protected == {"admin-manager", "cogs-loader"}
    assert "cda_admin" not in repr(items)


@pytest.mark.parametrize(
    "cog_id",
    [
        "../os",
        "../../subprocess",
        "os.system",
        "importlib",
        "/absolute/path",
        "module;shutdown",
        "new\nline",
        "a" * 1000,
    ],
)
def test_malicious_cog_ids_fail_before_adapter(cog_id):
    service, _, adapter, actor, _ = fixture_service()
    before = list(adapter.calls)
    with pytest.raises(ApplicationOperationError) as failure:
        run(service.reload_cog(actor, "cda-admin", cog_id, "request-1"))
    assert failure.value.code == "cog_not_found"
    assert adapter.calls == before


def test_load_unload_reload_and_protected_cog():
    service, _, adapter, actor, audits = fixture_service()
    extension = TRUSTED_CAPABILITY_CATALOG["unbot"].cogs["habbo-id-tracker"].extension
    run(service.unload_cog(actor, "unbot", "habbo-id-tracker", "request-1"))
    assert extension not in adapter.loaded["unbot"]
    loaded = run(service.load_cog(actor, "unbot", "habbo-id-tracker", "request-2"))
    assert loaded.status.value == "succeeded"
    assert run(service.reload_cog(actor, "unbot", "habbo-id-tracker", "request-3"))
    with pytest.raises(ApplicationOperationError) as protected:
        run(service.unload_cog(actor, "cda-admin", "cogs-loader", "request-4"))
    assert protected.value.code == "cog_not_unloadable"
    assert all("extension" not in repr(event) for event in audits)


def test_reload_all_partial_failure_is_deterministic_and_safe():
    service, _, adapter, actor, _ = fixture_service()
    adapter.failures[("reload", "unbot")] = RuntimeError("TOKEN=/secret raw traceback")
    operation = run(service.reload_all_cogs(actor, "unbot", "request-1"))
    assert operation.status.value == "partial"
    assert operation.result_summary == "0 succeeded; 3 failed"
    assert "TOKEN" not in repr(operation) and "/secret" not in repr(operation)


def test_command_sync_requires_stage8_ready_and_preserves_configured_scope():
    service, _, adapter, actor, _ = fixture_service()
    service._health.ready = False
    with pytest.raises(ApplicationOperationError) as not_ready:
        run(service.sync_commands(actor, "unbot", "request-1"))
    assert not_ready.value.code == "bot_not_ready"
    assert not any(call[0] == "sync" for call in adapter.calls)
    service._health.ready = True
    adapter.command_counts["unbot"] = 7
    operation = run(service.sync_commands(actor, "unbot", "request-2"))
    assert operation.result_summary == "7 commands synchronized (global)"


def test_stopped_and_process_instance_race_fail_closed():
    service, supervisor, adapter, actor, _ = fixture_service()
    supervisor.state = ProcessState.OFFLINE
    with pytest.raises(ApplicationOperationError) as stopped:
        run(service.reload_cog(actor, "unbot", "habbo-id-tracker", "request-1"))
    assert stopped.value.code == "bot_not_running"
    supervisor.state = ProcessState.RUNNING

    original = adapter.reload_cog

    async def restart_during_call(*args):
        await original(*args)
        supervisor.instance = "instance-b"

    adapter.reload_cog = restart_during_call
    with pytest.raises(ApplicationOperationError) as stale:
        run(service.reload_cog(actor, "unbot", "habbo-id-tracker", "request-2"))
    assert stale.value.code == "process_instance_changed"


def test_maintenance_is_typed_but_unsupported_when_real_bots_have_no_contract():
    service, _, adapter, actor, _ = fixture_service(
        permissions=PERMISSIONS | {"maintenance.view", "maintenance.manage"}
    )
    with pytest.raises(ApplicationOperationError) as unsupported:
        run(service.enable_maintenance(actor, "unbot", "request-1"))
    assert unsupported.value.code == "capability_not_supported"
    assert not any(call[0] == "maintenance.set" for call in adapter.calls)
