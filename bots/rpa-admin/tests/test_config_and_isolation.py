from pathlib import Path
from unittest.mock import patch

import pytest

from rpa_admin.common_paths import json_file
from rpa_admin.config import RPAAdminConfig
from shared.bot_core.exceptions import PathSecurityError, ValidationError


def test_config_requires_bot_specific_token(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="RPA_ADMIN_TOKEN"):
        RPAAdminConfig.from_env({"MDBO_RUNTIME_ROOT": str(tmp_path)})
    config = RPAAdminConfig.from_env(
        {"MDBO_RUNTIME_ROOT": str(tmp_path), "RPA_ADMIN_TOKEN": "test-token"}
    )
    assert config.token == "test-token"
    assert config.paths.bot_data("rpa-admin").path == tmp_path / "data" / "rpa-admin"


def test_rpa_json_paths_are_cwd_independent_and_isolated(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"MDBO_RUNTIME_ROOT": str(tmp_path)}):
        path = json_file("VerifiedUsers.json")
        assert path == tmp_path / "data" / "rpa-admin" / "VerifiedUsers.json"
        assert "cda-admin" not in path.parts and "cda-pay" not in path.parts and "unbot" not in path.parts


def test_json_filename_rejects_traversal(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"MDBO_RUNTIME_ROOT": str(tmp_path)}):
        with pytest.raises(PathSecurityError):
            json_file("../cda-admin/state.json")
