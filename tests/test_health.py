from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from shared.heartbeat import (
    Heartbeat,
    HeartbeatReporter,
    HeartbeatValidationError,
    decode_heartbeat,
)
from supervisor.health import (
    CanonicalState,
    DesiredState,
    HealthEvidence,
    HealthStore,
    HealthTiming,
    HeartbeatReceiver,
    reconcile,
)
from supervisor.systemd import SystemdEvidenceAdapter


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def heartbeat(bot="cda-admin", instance=None, sequence=1, connected=True, ready=True):
    return Heartbeat(
        1,
        bot,
        instance or str(uuid4()),
        sequence,
        datetime.now(timezone.utc),
        connected,
        ready,
        False,
    )


def base(**changes):
    value = HealthEvidence("cda-admin", True, DesiredState.RUNNING, True, True, "instance", 90.0)
    return replace(value, **changes)


@pytest.mark.parametrize(
    ("changes", "state"),
    [
        ({"enabled": False}, CanonicalState.DISABLED),
        ({"crash_loop": True}, CanonicalState.CRASH_LOOP),
        ({"restarting": True}, CanonicalState.RESTARTING),
        ({"maintenance_confirmed": True}, CanonicalState.MAINTENANCE),
        ({"process_running": False, "unexpected_exit": True}, CanonicalState.CRASHED),
        ({"process_running": False, "desired": DesiredState.STOPPED}, CanonicalState.OFFLINE),
        ({"identity_verified": False}, CanonicalState.UNKNOWN),
        ({}, CanonicalState.STARTING),
    ],
)
def test_reconciliation_precedence(changes, state):
    assert reconcile(base(**changes), 100, HealthTiming())[0] is state


@pytest.mark.anyio
async def test_heartbeat_fresh_stale_recovery_and_old_instance_isolation():
    clock = Clock()
    store = HealthStore(HealthTiming(freshness_threshold=10), monotonic=clock)
    instance = str(uuid4())
    await store.set_evidence(base(process_instance_id=instance, process_started_monotonic=0))
    first = heartbeat(instance=instance)
    assert await store.accept_heartbeat("cda-admin", first)
    assert (await store.get("cda-admin")).state is CanonicalState.ONLINE
    assert not await store.accept_heartbeat("cda-admin", replace(first, sequence=0))
    assert not await store.accept_heartbeat("cda-admin", heartbeat(instance=str(uuid4())))
    assert not await store.accept_heartbeat("cda-pay", heartbeat("cda-pay", instance))
    clock.value += 11
    assert (await store.get("cda-admin")).state is CanonicalState.UNKNOWN
    assert await store.accept_heartbeat("cda-admin", replace(first, sequence=2))
    assert (await store.get("cda-admin")).state is CanonicalState.ONLINE


def test_schema_strict_validation_security():
    item = heartbeat()
    assert decode_heartbeat(item.encode(), allowed_bot_ids=frozenset({"cda-admin"})) == item
    for payload in (
        b"{}",
        b"not json",
        b"x" * 2049,
        item.encode().replace(b'"schema_version":1', b'"schema_version":2'),
    ):
        with pytest.raises(HeartbeatValidationError):
            decode_heartbeat(payload, allowed_bot_ids=frozenset({"cda-admin"}))
    with pytest.raises(HeartbeatValidationError):
        decode_heartbeat(
            replace(item, bot_id="cda-pay").encode(), allowed_bot_ids=frozenset({"cda-admin"})
        )
    assert "TOKEN" not in set(Heartbeat.__dataclass_fields__)


@pytest.mark.anyio
async def test_receiver_and_reporter_recover_without_discord(tmp_path: Path):
    clock = Clock()
    instance = str(uuid4())
    store = HealthStore(monotonic=clock)
    await store.set_evidence(base(process_instance_id=instance))
    path = tmp_path / "health.sock"
    reporter = HeartbeatReporter(
        "cda-admin", socket_path=path, process_instance_id=instance, cadence=0.01
    )
    assert not await reporter.emit()  # unavailable is harmless
    receiver = HeartbeatReceiver(str(path), store, frozenset({"cda-admin"}))
    await receiver.start()
    await reporter.on_ready()
    for _ in range(30):
        if (await store.get("cda-admin")).state is CanonicalState.ONLINE:
            break
        await asyncio.sleep(0.01)
    assert (await store.get("cda-admin")).state is CanonicalState.ONLINE
    await reporter.on_disconnect()
    await asyncio.sleep(0.02)
    assert (await store.get("cda-admin")).evidence.process_running
    await reporter.close()
    await receiver.close()


@pytest.mark.anyio
async def test_concurrent_writes_are_serialized():
    clock = Clock()
    instance = str(uuid4())
    store = HealthStore(monotonic=clock)
    await store.set_evidence(base(process_instance_id=instance))
    results = await asyncio.gather(
        *(
            store.accept_heartbeat("cda-admin", heartbeat(instance=instance, sequence=n))
            for n in range(1, 20)
        )
    )
    assert any(results)
    assert (await store.get("cda-admin")).evidence.heartbeat.sequence == 19


class FakeSystemd:
    async def properties(self, unit):
        return {
            "Id": unit,
            "ActiveState": "active",
            "SubState": "running",
            "MainPID": 42,
            "InvocationID": "inv",
            "ControlGroup": "/system.slice/" + unit,
            "JournalCursor": "cursor",
        }


@pytest.mark.anyio
async def test_systemd_allowlist_and_strong_identity():
    adapter = SystemdEvidenceAdapter(FakeSystemd())
    evidence = await adapter.evidence_for("cda-admin")
    assert evidence.unit_name == "mdbo-cda-admin.service"
    assert adapter.identity_verified(evidence, evidence)
    assert not adapter.identity_verified(replace(evidence, main_pid=43), evidence)
    assert not adapter.identity_verified(replace(evidence, invocation_id="other"), evidence)
    assert not adapter.identity_verified(replace(evidence, control_group="other"), evidence)
    with pytest.raises(Exception):
        await adapter.evidence_for("../../evil.service")


def test_discord_connected_and_ready_are_separate():
    hb = heartbeat(instance="00000000-0000-0000-0000-000000000000", ready=False)
    evidence = base(
        process_instance_id=hb.process_instance_id,
        process_started_monotonic=0,
        heartbeat=hb,
        heartbeat_received_monotonic=100,
    )
    assert reconcile(evidence, 100, HealthTiming())[0] is CanonicalState.DISCONNECTED
    assert (
        reconcile(
            replace(evidence, heartbeat=replace(hb, discord_ready=True)), 100, HealthTiming()
        )[0]
        is CanonicalState.ONLINE
    )
