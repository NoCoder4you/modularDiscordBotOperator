from types import SimpleNamespace

import pytest

from shared.bot_core import PathSecurityError, ValidationError
from cda_pay.config import CDAPayConfig


def test_configuration_requires_only_cda_pay_token(tmp_path):
    cfg = CDAPayConfig.from_env({"CDA_PAY_TOKEN": "pay-token", "MDBO_RUNTIME_ROOT": str(tmp_path)})
    assert cfg.token == "pay-token"
    assert cfg.paths.bot_data("cda-pay").path == (tmp_path / "data" / "cda-pay").resolve()
    with pytest.raises(ValidationError, match="CDA_PAY_TOKEN"):
        CDAPayConfig.from_env({"MDBO_RUNTIME_ROOT": str(tmp_path)})


def test_runtime_path_rejects_traversal(tmp_path):
    cfg = CDAPayConfig.from_env({"MDBO_RUNTIME_ROOT": str(tmp_path)}, require_token=False)
    with pytest.raises(PathSecurityError):
        cfg.paths.bot_data("cda-pay", "..", "cda-admin", "state.json")


def test_cog_paths_are_isolated_from_cda_admin(monkeypatch, tmp_path):
    monkeypatch.setenv("MDBO_RUNTIME_ROOT", str(tmp_path))
    import importlib
    import cda_pay.cogs.paths as paths

    paths = importlib.reload(paths)
    assert paths.JSON_DIR.is_relative_to((tmp_path / "data" / "cda-pay").resolve())
    assert "cda-admin" not in paths.JSON_DIR.parts


def test_payer_and_trial_payer_permissions(monkeypatch, tmp_path):
    pytest.importorskip("discord")
    pytest.importorskip("apscheduler")
    monkeypatch.setenv("MDBO_RUNTIME_ROOT", str(tmp_path))
    from cda_pay.cogs import PayVoid, RecordPay

    payer = SimpleNamespace(user=SimpleNamespace(roles=[SimpleNamespace(name="Payer")]))
    trial = SimpleNamespace(roles=[SimpleNamespace(name="Trial Payer")])
    assert RecordPay.has_payer_role(payer)
    assert not RecordPay.has_payer_role(SimpleNamespace(user=trial))
    assert PayVoid.has_payer_role(trial)


def test_void_schema_reset_and_persistence(monkeypatch, tmp_path):
    pytest.importorskip("discord")
    pytest.importorskip("apscheduler")
    monkeypatch.setenv("MDBO_RUNTIME_ROOT", str(tmp_path))
    import importlib
    import cda_pay.cogs.paths as paths
    paths = importlib.reload(paths)
    import cda_pay.cogs.PayVoid as module
    module = importlib.reload(module)

    module.ensure_file()
    assert module.json.loads(module.VOID_DATA_FILE.read_text()) == {"voids": {}}
    cog = object.__new__(module.PayVoid)
    cog.data = {"voids": {"example": {"void_count": 2, "ban_until": None}}}
    cog.save()
    cog.reset_voids()
    assert module.json.loads(module.VOID_DATA_FILE.read_text()) == {"voids": {}}
