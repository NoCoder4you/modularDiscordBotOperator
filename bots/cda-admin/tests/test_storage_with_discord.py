import pytest
pytest.importorskip("discord", reason="CDA Admin runtime dependencies are not installed")

import importlib
import json


def test_admin_json_round_trip_preserves_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("MDBO_RUNTIME_ROOT", str(tmp_path))
    module = importlib.import_module("cda_admin.cogs.AdminManager")
    module = importlib.reload(module)
    module._save_admins({22, 11})
    assert json.loads(module._ADMIN_JSON.read_text()) == {"admins": [11, 22]}


def test_niceblock_round_trip_preserves_list_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("MDBO_RUNTIME_ROOT", str(tmp_path))
    module = importlib.import_module("cda_admin.cogs.nice")
    module = importlib.reload(module)
    module.save_enabled_users([101, 202])
    assert module.load_enabled_users() == [101, 202]
