"""State model that keeps process and Discord readiness independent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class BotState(StrEnum):
    ONLINE = "online"
    STARTING = "starting"
    RESTARTING = "restarting"
    DISCONNECTED = "disconnected"
    CRASHED = "crashed"
    CRASH_LOOP = "crash_loop"
    MAINTENANCE = "maintenance"
    DISABLED = "disabled"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BotStatus:
    state: BotState
    process_running: bool
    discord_connected: bool = False
    discord_ready: bool = False
    heartbeat_at: datetime | None = None
    pid: int | None = None
    generation: int = 0

    def heartbeat_fresh(self, *, now: datetime | None = None, max_age_seconds: float = 30) -> bool:
        if self.heartbeat_at is None or max_age_seconds < 0:
            return False
        current = now or datetime.now(timezone.utc)
        heartbeat = self.heartbeat_at
        if heartbeat.tzinfo is None:
            return False
        return (current - heartbeat).total_seconds() <= max_age_seconds
