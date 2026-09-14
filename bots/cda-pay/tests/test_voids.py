from datetime import datetime

from cda_pay.voids import record_void


def test_third_void_creates_rounded_24_hour_ban_and_preserves_schema():
    record = {"void_count": 2, "ban_until": None}
    result = record_void(record, datetime(2026, 7, 3, 15, 37, 12))
    assert result.banned
    assert record == {"void_count": 0, "ban_until": "2026-07-04T15:00:00"}


def test_active_ban_restarts_from_now_rather_than_extending_old_expiry():
    record = {"void_count": 0, "ban_until": "2026-07-05T20:00:00"}
    record_void(record, datetime(2026, 7, 4, 10, 45))
    assert record["ban_until"] == "2026-07-05T10:00:00"


def test_expired_ban_clears_and_new_void_counts_as_first():
    record = {"void_count": 0, "ban_until": "2026-07-03T09:00:00"}
    result = record_void(record, datetime(2026, 7, 3, 9, 0, 1))
    assert not result.banned
    assert record == {"void_count": 1, "ban_until": None}
