from types import SimpleNamespace

import pytest

pytest.importorskip("discord")
pytest.importorskip("apscheduler")

from cda_pay.cogs.RecordPay import PayTracker, calculate_week_start, generate_unique_id


def test_record_json_schema_and_totals_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("MDBO_RUNTIME_ROOT", str(tmp_path))
    import importlib
    import cda_pay.cogs.paths as paths
    import cda_pay.cogs.RecordPay as module
    importlib.reload(paths)
    module = importlib.reload(module)

    tracker = PayTracker(SimpleNamespace())
    assert tracker.pay_data == {"records": {}, "daily_totals": {}, "weekly_totals": {}}
    tracker.pay_data["records"]["2026-06-01"] = [{"record_id": "12345", "total_paid": 50}]
    tracker.save_data()
    assert tracker.load_data() == tracker.pay_data
    assert tracker.file_path.is_relative_to((tmp_path / "data" / "cda-pay").resolve())


def test_weekly_key_and_unique_id_shape():
    assert calculate_week_start("2026-01-01") == "2025-12-29"
    generated = generate_unique_id({"10000", "99999"})
    assert len(generated) == 5 and generated.isdigit()
