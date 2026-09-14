from pathlib import Path

import pytest

from shared.bot_core.exceptions import ValidationError
from unbot.config import UnbotConfig
from unbot.paths import data_root


def test_token_is_required_and_not_given_a_default():
    with pytest.raises(ValidationError, match="UNBOT_TOKEN"):
        UnbotConfig.from_env({})
    assert UnbotConfig.from_env({"UNBOT_TOKEN": " local-secret "}).token == "local-secret"


def test_data_root_is_isolated_from_other_bots(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MDBO_RUNTIME_ROOT", str(tmp_path))
    root = data_root()
    assert root == (tmp_path / "data" / "unbot").resolve()
    assert not root.is_relative_to((tmp_path / "data" / "cda-admin").resolve())
    assert not root.is_relative_to((tmp_path / "data" / "cda-pay").resolve())
