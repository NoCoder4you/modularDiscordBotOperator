"""Pure state transition for CDA Pay's source-compatible void/ban rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, MutableMapping


@dataclass(frozen=True, slots=True)
class VoidResult:
    banned: bool
    void_count: int
    ban_until: datetime | None


def record_void(record: MutableMapping[str, Any], now: datetime) -> VoidResult:
    """Apply one void, preserving naive ISO serialization and hour rounding."""
    serialized = record.get("ban_until")
    if serialized:
        active_until = datetime.fromisoformat(serialized)
        if active_until > now:
            new_until = (now + timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
            record["ban_until"] = new_until.isoformat()
            return VoidResult(True, int(record.get("void_count", 0)), new_until)
        record.update({"void_count": 0, "ban_until": None})

    count = int(record.get("void_count", 0)) + 1
    if count >= 3:
        ban_until = (now + timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
        record.update({"void_count": 0, "ban_until": ban_until.isoformat()})
        return VoidResult(True, 0, ban_until)

    record.update({"void_count": count, "ban_until": None})
    return VoidResult(False, count, None)
