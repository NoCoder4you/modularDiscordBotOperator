from datetime import datetime, timedelta, timezone
import json
import os
import stat
import pytest
from shared.bot_core import BotState, BotStatus, PlatformConfig, ValidationError
from shared.bot_core.jsonio import atomic_write_json


def test_environment_config_validation(tmp_path):
    config = PlatformConfig.from_env(
        {"MDBO_RUNTIME_ROOT": str(tmp_path), "MDBO_LOG_LEVEL": "warning"}
    )
    assert config.log_level == "WARNING"
    with pytest.raises(ValidationError):
        PlatformConfig.from_env({"MDBO_LOG_LEVEL": "LOUD"})


def test_status_does_not_infer_online_from_process():
    status = BotStatus(BotState.STARTING, process_running=True, discord_connected=False)
    assert status.state is BotState.STARTING and not status.discord_ready


def test_heartbeat_freshness():
    now = datetime.now(timezone.utc)
    status = BotStatus(BotState.ONLINE, True, True, True, now - timedelta(seconds=5))
    assert status.heartbeat_fresh(now=now, max_age_seconds=10)
    assert not status.heartbeat_fresh(now=now, max_age_seconds=1)


@pytest.mark.parametrize("future_offset", [timedelta(microseconds=1), timedelta(days=1)])
def test_future_heartbeat_is_not_fresh(future_offset):
    now = datetime.now(timezone.utc)
    status = BotStatus(BotState.ONLINE, True, True, True, now + future_offset)

    assert not status.heartbeat_fresh(now=now, max_age_seconds=30)


def test_heartbeat_at_current_time_is_fresh():
    now = datetime.now(timezone.utc)
    status = BotStatus(BotState.ONLINE, True, True, True, now)

    assert status.heartbeat_fresh(now=now, max_age_seconds=0)


def test_atomic_json_write(tmp_path):
    target = tmp_path / "nested" / "state.json"
    atomic_write_json(target, {"healthy": True})
    assert json.loads(target.read_text()) == {"healthy": True}
    assert not list(target.parent.glob("*.tmp"))


@pytest.mark.skipif(os.name != "posix", reason="directory fsync is a POSIX durability step")
def test_atomic_json_write_syncs_file_and_directories(tmp_path, monkeypatch):
    synced_modes = []
    real_fsync = os.fsync

    def recording_fsync(descriptor):
        synced_modes.append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    atomic_write_json(tmp_path / "new" / "nested" / "state.json", {"healthy": True})

    assert any(stat.S_ISREG(mode) for mode in synced_modes)
    # Both newly created directories, their existing parent, and the renamed
    # file's containing directory must be persisted.
    assert sum(stat.S_ISDIR(mode) for mode in synced_modes) >= 4
