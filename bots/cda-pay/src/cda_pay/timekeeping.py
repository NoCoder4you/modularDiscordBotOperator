"""Explicit UK wall-clock helpers preserving CDA Pay's external date formats."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
PAY_RANGES = (
    (0, 1, "12-1 AM"), (1, 2, "1-2 AM"), (6, 7, "6-7 AM"), (7, 8, "7-8 AM"),
    (12, 13, "12-1 PM"), (13, 14, "1-2 PM"), (18, 19, "6-7 PM"), (19, 20, "7-8 PM"),
)


def london_now() -> datetime:
    return datetime.now(LONDON)


def monthly_filename(now: datetime | None = None) -> str:
    current = now.astimezone(LONDON) if now and now.tzinfo else (now or london_now())
    return current.strftime("%b_%Y").upper() + ".json"


def pay_time(now: datetime | None = None) -> tuple[str | tuple[str, str], str]:
    current = now.astimezone(LONDON) if now and now.tzinfo else (now or london_now())
    for index, (start, end, label) in enumerate(PAY_RANGES):
        if start <= current.hour < end:
            if current.minute < 25 and index > 0:
                return (PAY_RANGES[index - 1][2], label), current.strftime("%Y-%m-%d")
            if current.minute >= 50 and index < len(PAY_RANGES) - 1:
                return (label, PAY_RANGES[index + 1][2]), current.strftime("%Y-%m-%d")
            return label, current.strftime("%Y-%m-%d")
    previous = current - timedelta(hours=1)
    label = next(
        (label for start, end, label in reversed(PAY_RANGES) if start <= previous.hour < end),
        "4-5 PM",
    )
    return label, previous.strftime("%Y-%m-%d")


def week_start(date_string: str) -> str:
    day = datetime.strptime(date_string, "%Y-%m-%d")
    return (day - timedelta(days=day.weekday())).strftime("%Y-%m-%d")
