from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from portal.identity import SQLiteIdentityStore, hash_password
from portal.management import DenyByDefaultAuthorizer
from portal.scheduler import (
    ADMINISTRATIVE_TASK_CATALOG,
    ExecutionStatus,
    MIN_INTERVAL_SECONDS,
    Schedule,
    SchedulerError,
    SchedulerService,
    SQLiteSchedulerStore,
    next_run,
)

UTC = timezone.utc


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Adapter:
    def __init__(self):
        self.calls = []

    async def execute(self, task, actor, request_id):
        self.calls.append((task.task_type_id, task.bot_id, actor.principal_id, request_id))
        return "operation-safe-id"


@pytest.fixture
def scheduler(tmp_path):
    identities = SQLiteIdentityStore(tmp_path / "identities.db")
    identity = identities.create(
        "operator",
        hash_password("correct horse battery staple"),
        frozenset(
            {
                "scheduler.view",
                "scheduler.manage",
                "scheduler.run",
                "bots.restart",
                "commands.sync",
                "backups.create",
            }
        ),
        frozenset({"cda-admin", "unbot"}),
    )
    clock = Clock(datetime(2026, 1, 1, 12, tzinfo=UTC))
    adapter = Adapter()
    service = SchedulerService(
        SQLiteSchedulerStore(tmp_path / "scheduler.db", history_per_task=2),
        identities,
        DenyByDefaultAuthorizer(),
        adapter,
        clock=clock,
        max_total=3,
        max_per_owner_bot=2,
    )
    return service, identity, identities, adapter, clock


def test_catalog_is_closed_and_contains_no_executable_payload():
    assert set(ADMINISTRATIVE_TASK_CATALOG) == {"backup.create", "bot.restart", "commands.sync"}
    assert all(
        "command" not in item.parameter_names for item in ADMINISTRATIVE_TASK_CATALOG.values()
    )


def test_schedule_calculation_timezone_and_dst():
    spring = Schedule("daily", "Europe/London", local_time="01:30")
    # 01:30 does not exist on 29 March 2026, so the occurrence is skipped.
    assert next_run(spring, datetime(2026, 3, 28, 2, tzinfo=UTC)) == datetime(
        2026, 3, 30, 0, 30, tzinfo=UTC
    )
    autumn = Schedule("daily", "Europe/London", local_time="01:30")
    # Ambiguous wall time uses fold=0 (the first occurrence) exactly once.
    assert next_run(autumn, datetime(2026, 10, 24, 2, tzinfo=UTC)) == datetime(
        2026, 10, 25, 0, 30, tzinfo=UTC
    )
    weekly = Schedule("weekly", "UTC", local_time="10:00", weekdays=(0,))
    assert next_run(weekly, datetime(2026, 1, 1, tzinfo=UTC)).weekday() == 0


def test_interval_minimum_and_invalid_timezone():
    with pytest.raises(SchedulerError, match="minimum"):
        next_run(
            Schedule("interval", "UTC", interval_seconds=MIN_INTERVAL_SECONDS - 1),
            datetime.now(UTC),
        )
    with pytest.raises(SchedulerError) as error:
        next_run(Schedule("daily", "EST", local_time="10:00"), datetime.now(UTC))
    assert error.value.code == "timezone_invalid"


def test_create_requires_scheduler_and_underlying_exact_bot(scheduler):
    service, identity, *_ = scheduler
    weak = replace(identity, permissions=frozenset({"scheduler.manage", "scheduler.view"}))
    with pytest.raises(SchedulerError) as error:
        service.create(
            weak.principal(),
            name="restart",
            bot_id="unbot",
            task_type_id="bot.restart",
            schedule=Schedule("daily", "UTC", local_time="13:00"),
            parameters={},
        )
    assert error.value.code == "permission_denied"
    wrong_bot = replace(identity, bot_ids=frozenset({"unbot"}))
    with pytest.raises(SchedulerError):
        service.create(
            wrong_bot.principal(),
            name="restart",
            bot_id="cda-admin",
            task_type_id="bot.restart",
            schedule=Schedule("daily", "UTC", local_time="13:00"),
            parameters={},
        )


def test_revision_delete_quota_and_idor(scheduler):
    service, identity, *_ = scheduler
    task = service.create(
        identity.principal(),
        name="restart",
        bot_id="unbot",
        task_type_id="bot.restart",
        schedule=Schedule("daily", "UTC", local_time="13:00"),
        parameters={},
    )
    with pytest.raises(SchedulerError) as error:
        service.update(
            identity.principal(), task.task_id, 0, name="new", schedule=task.schedule, parameters={}
        )
    assert error.value.code == "stale_revision"
    outsider = replace(identity, bot_ids=frozenset({"cda-admin"}))
    with pytest.raises(SchedulerError) as hidden:
        service.get_task(outsider.principal(), task.task_id)
    assert hidden.value.code == "scheduled_task_not_found"
    service.create(
        identity.principal(),
        name="sync",
        bot_id="unbot",
        task_type_id="commands.sync",
        schedule=Schedule("daily", "UTC", local_time="14:00"),
        parameters={},
    )
    with pytest.raises(SchedulerError) as quota:
        service.create(
            identity.principal(),
            name="third",
            bot_id="unbot",
            task_type_id="bot.restart",
            schedule=Schedule("daily", "UTC", local_time="15:00"),
            parameters={},
        )
    assert quota.value.code == "scheduler_limit_reached"
    service.delete(identity.principal(), task.task_id, task.revision)
    assert service.store.get(task.task_id) is None


def test_permission_revocation_suspends_and_does_not_execute(scheduler):
    service, identity, identities, adapter, clock = scheduler
    task = service.create(
        identity.principal(),
        name="restart",
        bot_id="unbot",
        task_type_id="bot.restart",
        schedule=Schedule("daily", "UTC", local_time="13:00"),
        parameters={},
    )
    identities.admin_update(
        identity.identity_id, permissions=identity.permissions - {"bots.restart"}
    )
    clock.now = datetime(2026, 1, 1, 13, tzinfo=UTC)
    result = asyncio.run(service.run_due())
    assert not adapter.calls
    assert service.store.history(task.task_id)[0].status is ExecutionStatus.AUTHORIZATION_REVOKED
    assert service.store.get(task.task_id).suspended_reason == "authorization_revoked"
    assert result


def test_disabled_owner_and_misfire_fail_closed(scheduler):
    service, identity, identities, adapter, clock = scheduler
    task = service.create(
        identity.principal(),
        name="restart",
        bot_id="unbot",
        task_type_id="bot.restart",
        schedule=Schedule("daily", "UTC", local_time="13:00"),
        parameters={},
    )
    identities.set_enabled(identity.identity_id, False)
    clock.now += timedelta(hours=1)
    asyncio.run(service.run_due())
    assert not adapter.calls
    assert service.store.history(task.task_id)[0].status is ExecutionStatus.AUTHORIZATION_REVOKED


def test_run_now_does_not_shift_schedule_and_duplicate_claim_is_durable(scheduler):
    service, identity, _, adapter, _ = scheduler
    task = service.create(
        identity.principal(),
        name="restart",
        bot_id="unbot",
        task_type_id="bot.restart",
        schedule=Schedule("daily", "UTC", local_time="13:00"),
        parameters={},
    )
    original = task.next_run_at
    asyncio.run(service.run_now(identity.principal(), task.task_id, "request-one"))
    assert service.store.get(task.task_id).next_run_at == original
    assert len(adapter.calls) == 1
    asyncio.run(service.run_now(identity.principal(), task.task_id, "request-two"))
    assert len(adapter.calls) == 2


def test_running_execution_recovery_is_unknown(scheduler):
    service, identity, *_ = scheduler
    task = service.create(
        identity.principal(),
        name="restart",
        bot_id="unbot",
        task_type_id="bot.restart",
        schedule=Schedule("daily", "UTC", local_time="13:00"),
        parameters={},
    )
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert service.store.claim(task, now, now, "r")
    assert service.store.recover_running(now + timedelta(minutes=1)) == 1
    assert service.store.history(task.task_id)[0].status is ExecutionStatus.UNKNOWN


def test_injection_payloads_are_rejected(scheduler):
    service, identity, *_ = scheduler
    for value in ("../", "$(id)", "https://example.test", "x\ncommand"):
        with pytest.raises(SchedulerError):
            service.create(
                identity.principal(),
                name=value,
                bot_id="unbot",
                task_type_id="bot.restart",
                schedule=Schedule("daily", "UTC", local_time="13:00"),
                parameters={},
            )
    with pytest.raises(SchedulerError):
        service.create(
            identity.principal(),
            name="bad",
            bot_id="unbot",
            task_type_id="python.eval",
            schedule=Schedule("daily", "UTC", local_time="13:00"),
            parameters={"python": "1+1"},
        )
