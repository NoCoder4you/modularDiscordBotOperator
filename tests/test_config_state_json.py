from datetime import datetime, timedelta, timezone
import json
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


def test_atomic_json_write(tmp_path):
    target = tmp_path / "nested" / "state.json"
    atomic_write_json(target, {"healthy": True})
    assert json.loads(target.read_text()) == {"healthy": True}
    assert not list(target.parent.glob("*.tmp"))
