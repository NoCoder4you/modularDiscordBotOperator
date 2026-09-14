from pathlib import Path
from unittest.mock import patch

from rpa_admin.common_paths import cogs_dir, cogs_file, json_dir, json_file


def test_runtime_json_helpers_and_packaged_cogs(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"MDBO_RUNTIME_ROOT": str(tmp_path)}):
        assert json_dir() == tmp_path / "data" / "rpa-admin"
        assert json_file("example.json") == json_dir() / "example.json"
    assert cogs_file("example.py") == cogs_dir() / "example.py"
    assert cogs_dir().name == "cogs"
