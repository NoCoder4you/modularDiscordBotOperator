"""Narrow typed systemd evidence boundary; transport is injected (D-Bus in production)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from .errors import UnknownBotError

TRUSTED_UNITS = {
    "cda-admin": "mdbo-cda-admin.service",
    "cda-pay": "mdbo-cda-pay.service",
    "unbot": "mdbo-unbot.service",
    "rpa-admin": "mdbo-rpa-admin.service",
}


@dataclass(frozen=True, slots=True)
class UnitEvidence:
    bot_id: str
    unit_name: str
    active_state: str
    sub_state: str
    main_pid: int
    invocation_id: str | None
    control_group: str | None
    journal_cursor: str | None = None


class SystemdTransport(Protocol):
    async def properties(self, unit_name: str) -> dict[str, object]: ...


class SystemdEvidenceAdapter:
    def __init__(self, transport: SystemdTransport) -> None:
        self._transport = transport

    async def evidence_for(self, bot_id: str) -> UnitEvidence:
        try:
            unit = TRUSTED_UNITS[bot_id]
        except KeyError as exc:
            raise UnknownBotError("unknown bot") from exc
        raw = await self._transport.properties(unit)
        if raw.get("Id") != unit:
            raise ValueError("systemd returned mismatched unit identity")
        return UnitEvidence(
            bot_id,
            unit,
            str(raw.get("ActiveState", "unknown")),
            str(raw.get("SubState", "unknown")),
            int(cast(str | bytes | int, raw.get("MainPID", 0))),
            str(raw["InvocationID"]) if raw.get("InvocationID") else None,
            str(raw["ControlGroup"]) if raw.get("ControlGroup") else None,
            str(raw["JournalCursor"]) if raw.get("JournalCursor") else None,
        )

    @staticmethod
    def identity_verified(current: UnitEvidence, saved: UnitEvidence) -> bool:
        return (
            current.bot_id == saved.bot_id
            and current.unit_name == saved.unit_name
            and current.main_pid > 0
            and current.main_pid == saved.main_pid
            and bool(current.invocation_id)
            and current.invocation_id == saved.invocation_id
            and bool(current.control_group)
            and current.control_group == saved.control_group
        )
