import json
from pathlib import Path

import pytest
from shared.bot_core import ValidationError

from cda_admin.config import CDAAdminConfig
from cda_admin.cogs.paths import data_path


def test_config_requires_token_only_for_runtime():
    with pytest.raises(ValidationError, match="CDA_ADMIN_TOKEN"):
        CDAAdminConfig.from_env({"MDBO_RUNTIME_ROOT": "runtime"})
    config = CDAAdminConfig.from_env(
        {"MDBO_RUNTIME_ROOT": "elsewhere", "MDBO_LOG_LEVEL": "warning"},
        require_token=False,
    )
    assert config.token == ""
    assert config.runtime_root == Path("elsewhere")
    assert config.log_level == "WARNING"


def test_data_path_is_isolated_and_seeds_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("MDBO_RUNTIME_ROOT", str(tmp_path))
    server = data_path("JSON/server.json")
    assert server.is_relative_to(tmp_path / "data" / "cda-admin")
    assert json.loads(server.read_text())["verified_users"] == []
    assert not (tmp_path / "data" / "cda-pay").exists()


def test_data_path_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("MDBO_RUNTIME_ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="relative"):
        data_path("../cda-pay/server.json")

