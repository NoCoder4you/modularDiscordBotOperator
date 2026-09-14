from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cda_pay.timekeeping import monthly_filename, pay_time, week_start

LONDON = ZoneInfo("Europe/London")


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (datetime(2026, 1, 5, 0, 25, tzinfo=LONDON), ("12-1 AM", "2026-01-05")),
        (datetime(2026, 7, 5, 19, 25, tzinfo=LONDON), ("7-8 PM", "2026-07-05")),
        (datetime(2026, 7, 5, 19, 50, tzinfo=LONDON), ("7-8 PM", "2026-07-05")),
        (datetime(2026, 7, 6, 0, 10, tzinfo=LONDON), ("12-1 AM", "2026-07-06")),
        (datetime(2026, 7, 6, 5, 30, tzinfo=LONDON), ("4-5 PM", "2026-07-06")),
    ],
)
def test_pay_window_characterization(instant, expected):
    assert pay_time(instant) == expected


def test_boundary_returns_source_adjacent_options_even_across_gap():
    assert pay_time(datetime(2026, 6, 2, 6, 24, tzinfo=LONDON)) == (
        ("1-2 AM", "6-7 AM"),
        "2026-06-02",
    )


def test_aware_utc_input_uses_london_wall_time_in_gmt_and_bst():
    utc = ZoneInfo("UTC")
    assert pay_time(datetime(2026, 1, 3, 18, 30, tzinfo=utc))[0] == "6-7 PM"
    assert pay_time(datetime(2026, 7, 3, 17, 30, tzinfo=utc))[0] == "6-7 PM"


def test_dst_transitions_produce_london_dates_without_crashing():
    assert pay_time(datetime(2026, 3, 29, 0, 30, tzinfo=LONDON))[1] == "2026-03-29"
    assert pay_time(datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=1))[1] == "2026-10-25"


def test_week_month_and_year_boundaries_preserve_keys():
    assert week_start("2026-07-05") == "2026-06-29"  # Sunday
    assert week_start("2026-07-06") == "2026-07-06"  # Monday
    assert monthly_filename(datetime(2026, 12, 31, 23, tzinfo=LONDON)) == "DEC_2026.json"
    assert monthly_filename(datetime(2027, 1, 1, 0, tzinfo=LONDON)) == "JAN_2027.json"
