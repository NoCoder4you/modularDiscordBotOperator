from __future__ import annotations

import asyncio
import os
import stat
import sys
from pathlib import Path

import pytest

from shared.bot_core.exceptions import ValidationError
from supervisor.controller import SubprocessController
from supervisor.errors import (
    BotAlreadyRunningError,
    BotAlreadyStoppedError,
    BotDisabledError,
    OperationInProgressError,
    ProcessIdentityError,
    ProcessStartError,
    UnknownBotError,
)
from supervisor.models import OperationStatus, ProcessState
from supervisor.registry import BotRegistry
from supervisor.service import SupervisorService
from supervisor.state import StateStore

IDS = ("cda-admin", "cda-pay", "unbot", "rpa-admin")

@pytest.fixture
def anyio_backend():
    return "asyncio"



def build_repository(tmp_path: Path, *, enabled: bool = True, timeout: float = 0.2) -> Path:
    root = tmp_path / "repo"
    (root / "bin").mkdir(parents=True)
    runner = root / "bin" / "python"
    runner.write_text(f"#!/bin/sh\nexec {sys.executable} \"$@\"\n", encoding="utf-8")
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)
    source = Path(__file__).parent / "support" / "fake_process.py"
    (root / "fake_process.py").write_bytes(source.read_bytes())
    for bot_id in IDS:
        directory = root / "bots" / bot_id
        directory.mkdir(parents=True)
        (directory / "bot.toml").write_text(
            f'''[bot]
id = "{bot_id}"
display_name = "{bot_id}"
entry_point = "fake_process"
working_directory = "."
enabled = {str(enabled).lower()}
startup_policy = "manual"
python_executable = "bin/python"
shutdown_timeout_seconds = {timeout}
''',
            encoding="utf-8",
        )
    return root


@pytest.fixture
async def service(tmp_path: Path):
    root = build_repository(tmp_path)
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": "must-not-be-inherited",
        **{bot_id.upper().replace("-", "_") + "_TOKEN": "fixture-secret" for bot_id in IDS},
    }
    instance = SupervisorService(
        BotRegistry(root, tmp_path / "runtime"),
        StateStore(tmp_path / "state" / "processes.json"),
        environment=environment,
        startup_grace_seconds=0.05,
    )
    await instance.startup()
    yield instance
    for bot in instance.list_bots():
        if instance.get_process_state(bot.bot_id) in {ProcessState.RUNNING, ProcessState.UNKNOWN}:
            try:
                await instance.stop(bot.bot_id)
            except Exception:
                pass
    await instance.shutdown()


def test_registry_loads_exact_catalog_and_rejects_hostile_ids(tmp_path: Path):
    registry = BotRegistry(build_repository(tmp_path), tmp_path / "runtime")
    assert {bot.bot_id for bot in registry.list()} == set(IDS)
    assert registry.get("cda-admin").token_environment_variable == "CDA_ADMIN_TOKEN"
    for value in ("../", "../../etc/passwd", "/etc/passwd", "C:\\bot", '"; rm -rf /', "x\ny", "unknown-bot"):
        with pytest.raises(UnknownBotError):
            registry.get(value)


def test_registry_rejects_entry_point_and_path_escape(tmp_path: Path):
    root = build_repository(tmp_path)
    manifest = root / "bots" / "unbot" / "bot.toml"
    manifest.write_text(manifest.read_text().replace("fake_process", "fake;command"))
    with pytest.raises(ValidationError):
        BotRegistry(root, tmp_path / "runtime")


@pytest.mark.anyio
async def test_disabled_and_secret_failure_are_safe(tmp_path: Path):
    root = build_repository(tmp_path, enabled=False)
    state = tmp_path / "state.json"
    supervisor = SupervisorService(BotRegistry(root, tmp_path / "run"), StateStore(state), environment={})
    await supervisor.startup()
    assert supervisor.get_process_state("unbot") is ProcessState.DISABLED
    with pytest.raises(BotDisabledError):
        await supervisor.start("unbot")
    assert "fixture-secret" not in state.read_text()
    await supervisor.shutdown()


@pytest.mark.anyio
async def test_start_stop_results_output_environment_and_idempotency(service):
    result = await service.start("cda-admin", actor="test-actor")
    assert result.current_state is ProcessState.RUNNING
    assert result.operation.status is OperationStatus.SUCCEEDED
    assert result.operation.operation_id
    assert service.get_process("cda-admin").pid > 0
    assert service.get_process("cda-admin").expected_argv[-2:] == ("-m", "fake_process")
    with pytest.raises(BotAlreadyRunningError):
        await service.start("cda-admin")
    await asyncio.sleep(0.05)
    lines = list(service.controller.output)
    assert {line.stream for line in lines} == {"stdout", "stderr"}
    assert all("fixture-secret" not in repr(line) for line in lines)
    stopped = await service.stop("cda-admin")
    assert stopped.current_state is ProcessState.OFFLINE
    with pytest.raises(BotAlreadyStoppedError):
        await service.stop("cda-admin")


@pytest.mark.anyio
async def test_restart_changes_instance_and_preserves_peer(service):
    first = await service.start("unbot")
    peer = await service.start("rpa-admin")
    restarted = await service.restart("unbot")
    assert restarted.process_instance_id != first.process_instance_id
    assert service.get_process("rpa-admin").process_instance_id == peer.process_instance_id
    await service.stop("unbot")
    assert service.get_process_state("rpa-admin") is ProcessState.RUNNING


@pytest.mark.anyio
async def test_immediate_and_unexpected_crashes(tmp_path: Path):
    root = build_repository(tmp_path)
    env = {"CDA_ADMIN_TOKEN": "x", "FAKE_MODE": "crash"}
    # Explicit fixture controls are intentionally not in the production allow-list;
    # use a controller wrapper to inject them without weakening environment policy.
    class CrashController(SubprocessController):
        async def spawn(self, record, argv, cwd, environment, callback):
            environment = dict(environment, FAKE_MODE="crash", FAKE_EXIT_CODE="23")
            return await super().spawn(record, argv, cwd, environment, callback)

    svc = SupervisorService(
        BotRegistry(root, tmp_path / "run"), StateStore(tmp_path / "state.json"),
        environment=env, controller=CrashController(), startup_grace_seconds=0.1,
    )
    await svc.startup()
    with pytest.raises(ProcessStartError):
        await svc.start("cda-admin")
    assert svc.get_process_state("cda-admin") is ProcessState.CRASHED
    assert svc.get_process("cda-admin").exit_code == 23
    await svc.shutdown()


@pytest.mark.anyio
async def test_forced_termination_is_bounded(tmp_path: Path):
    root = build_repository(tmp_path, timeout=0.05)
    class IgnoreController(SubprocessController):
        async def spawn(self, record, argv, cwd, environment, callback):
            return await super().spawn(record, argv, cwd, dict(environment, FAKE_MODE="ignore-term"), callback)
    svc = SupervisorService(
        BotRegistry(root, tmp_path / "run"), StateStore(tmp_path / "state.json"),
        environment={"CDA_PAY_TOKEN": "x"}, controller=IgnoreController(), startup_grace_seconds=0.05,
    )
    await svc.startup()
    await svc.start("cda-pay")
    for _ in range(20):
        if any(line.text == "ready" for line in svc.controller.output):
            break
        await asyncio.sleep(0.01)
    await svc.stop("cda-pay")
    assert svc.get_process("cda-pay").forced is True
    assert svc.get_process("cda-pay").exit_code < 0
    await svc.shutdown()


@pytest.mark.anyio
async def test_same_bot_rejected_while_different_bot_runs_concurrently(service):
    original = service.controller.spawn
    entered = asyncio.Event()
    release = asyncio.Event()
    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)
    service.controller.spawn = delayed
    first = asyncio.create_task(service.start("cda-admin"))
    await entered.wait()
    with pytest.raises(OperationInProgressError):
        await service.start("cda-admin")
    peer = asyncio.create_task(service.start("cda-pay"))
    release.set()
    await asyncio.gather(first, peer)
    assert service.get_process_state("cda-admin") is ProcessState.RUNNING
    assert service.get_process_state("cda-pay") is ProcessState.RUNNING


@pytest.mark.anyio
async def test_identity_mismatch_is_unknown_and_never_signalled(service, monkeypatch):
    await service.start("cda-admin")
    monkeypatch.setattr("supervisor.service.linux_process_identity", lambda _pid: (1, ("other",)))
    with pytest.raises(ProcessIdentityError):
        await service.stop("cda-admin")
    assert service.get_process_state("cda-admin") is ProcessState.UNKNOWN


def test_corrupt_and_stale_state_is_ignored(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text("not-json")
    assert StateStore(path).load() == []
