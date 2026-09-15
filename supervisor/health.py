"""Authoritative health evidence, reconciliation, and race-safe current store."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable

from shared.heartbeat import Heartbeat
from shared.heartbeat import MAX_HEARTBEAT_BYTES, HeartbeatValidationError, decode_heartbeat


class CanonicalState(StrEnum):
    DISABLED = "disabled"
    CRASH_LOOP = "crash_loop"
    RESTARTING = "restarting"
    MAINTENANCE = "maintenance"
    CRASHED = "crashed"
    OFFLINE = "offline"
    UNKNOWN = "unknown"
    STARTING = "starting"
    DISCONNECTED = "disconnected"
    ONLINE = "online"


class DesiredState(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class HealthTiming:
    emission_cadence: float = 10.0
    freshness_threshold: float = 30.0
    startup_health_timeout: float = 60.0


@dataclass(frozen=True, slots=True)
class HealthEvidence:
    bot_id: str
    enabled: bool
    desired: DesiredState
    process_running: bool
    identity_verified: bool
    process_instance_id: str | None
    process_started_monotonic: float | None
    heartbeat: Heartbeat | None = None
    heartbeat_received_monotonic: float | None = None
    restarting: bool = False
    maintenance_confirmed: bool = False
    unexpected_exit: bool = False
    crash_loop: bool = False
    process_conflict: bool = False

    def heartbeat_fresh(self, now: float, timing: HealthTiming) -> bool:
        return (
            self.heartbeat_received_monotonic is not None
            and now - self.heartbeat_received_monotonic <= timing.freshness_threshold
        )


def reconcile(
    evidence: HealthEvidence, now: float, timing: HealthTiming
) -> tuple[CanonicalState, str]:
    """Single deterministic precedence implementation; it never performs process actions."""
    if not evidence.enabled:
        return CanonicalState.DISABLED, "manifest_disabled"
    if evidence.crash_loop:
        return CanonicalState.CRASH_LOOP, "crash_loop_latched"
    if evidence.restarting:
        return CanonicalState.RESTARTING, "trusted_restart"
    if evidence.maintenance_confirmed:
        return CanonicalState.MAINTENANCE, "maintenance_confirmed"
    if evidence.unexpected_exit and not evidence.process_running:
        return CanonicalState.CRASHED, "unexpected_exit"
    if evidence.desired is DesiredState.STOPPED and not evidence.process_running:
        return CanonicalState.OFFLINE, "desired_stopped"
    if evidence.process_conflict or (evidence.process_running and not evidence.identity_verified):
        return CanonicalState.UNKNOWN, "process_identity_unverified"
    if not evidence.process_running:
        return CanonicalState.UNKNOWN, "process_evidence_missing"
    age = (
        now - evidence.process_started_monotonic
        if evidence.process_started_monotonic is not None
        else timing.startup_health_timeout + 1
    )
    if not evidence.heartbeat_fresh(now, timing):
        if age <= timing.startup_health_timeout:
            return CanonicalState.STARTING, "awaiting_fresh_heartbeat"
        return CanonicalState.UNKNOWN, "heartbeat_missing_or_stale"
    heartbeat = evidence.heartbeat
    if heartbeat is None:
        return CanonicalState.UNKNOWN, "heartbeat_missing"
    if not heartbeat.discord_connected or not heartbeat.discord_ready:
        if age <= timing.startup_health_timeout:
            return CanonicalState.STARTING, "awaiting_discord_ready"
        return CanonicalState.DISCONNECTED, "discord_not_ready"
    return CanonicalState.ONLINE, "fresh_ready_heartbeat"


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    evidence: HealthEvidence
    state: CanonicalState
    state_changed_at: datetime
    reason: str
    heartbeat_fresh: bool = False


@dataclass(frozen=True, slots=True)
class HealthEvent:
    name: str
    timestamp: datetime
    bot_id: str
    process_instance_id: str | None
    old_state: CanonicalState | None
    new_state: CanonicalState
    reason: str


class HealthStore:
    def __init__(
        self,
        timing: HealthTiming = HealthTiming(),
        *,
        monotonic: Callable[[], float],
        event_sink: Callable[[HealthEvent], None] | None = None,
    ) -> None:
        self.timing = timing
        self._monotonic = monotonic
        self._event_sink = event_sink
        self._items: dict[str, HealthSnapshot] = {}
        self._lock = asyncio.Lock()

    async def set_evidence(self, evidence: HealthEvidence) -> HealthSnapshot:
        async with self._lock:
            return self._set(evidence)

    async def accept_heartbeat(self, bot_id: str, heartbeat: Heartbeat) -> bool:
        async with self._lock:
            current = self._items.get(bot_id)
            if current is None or heartbeat.bot_id != bot_id:
                return False
            evidence = current.evidence
            previous = evidence.heartbeat
            if (
                not evidence.identity_verified
                or heartbeat.process_instance_id != evidence.process_instance_id
                or (previous is not None and heartbeat.sequence <= previous.sequence)
            ):
                return False
            self._set(
                replace(
                    evidence,
                    heartbeat=heartbeat,
                    heartbeat_received_monotonic=self._monotonic(),
                    maintenance_confirmed=heartbeat.maintenance,
                )
            )
            return True

    async def get(self, bot_id: str, *, refresh: bool = True) -> HealthSnapshot | None:
        async with self._lock:
            item = self._items.get(bot_id)
            if item and refresh:
                item = self._set(item.evidence)
            return item

    def _set(self, evidence: HealthEvidence) -> HealthSnapshot:
        state, reason = reconcile(evidence, self._monotonic(), self.timing)
        prior = self._items.get(evidence.bot_id)
        changed = prior is None or prior.state != state or prior.reason != reason
        changed_at = (
            datetime.now(timezone.utc) if changed or prior is None else prior.state_changed_at
        )
        result = HealthSnapshot(
            evidence, state, changed_at, reason, evidence.heartbeat_fresh(self._monotonic(), self.timing)
        )
        self._items[evidence.bot_id] = result
        if changed and self._event_sink:
            self._event_sink(
                HealthEvent(
                    "bot.state.changed",
                    changed_at,
                    evidence.bot_id,
                    evidence.process_instance_id,
                    prior.state if prior else None,
                    state,
                    reason,
                )
            )
        return result


class _DatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, receiver: "HeartbeatReceiver") -> None:
        self.receiver = receiver

    def datagram_received(self, data: bytes, _addr: object) -> None:
        asyncio.create_task(self.receiver.receive(data))


class HeartbeatReceiver:
    """Local Unix datagram receiver; filesystem permissions are the transport credential."""

    def __init__(self, path: str, store: HealthStore, allowed_bot_ids: frozenset[str]) -> None:
        self.path = path
        self.store = store
        self.allowed_bot_ids = allowed_bot_ids
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _DatagramProtocol(self),
            family=__import__("socket").AF_UNIX,
            local_addr=self.path,
        )
        self._transport = transport
        os.chmod(self.path, 0o600)

    async def close(self) -> None:
        if self._transport:
            self._transport.close()
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    async def receive(self, payload: bytes) -> bool:
        if len(payload) > MAX_HEARTBEAT_BYTES:
            return False
        try:
            heartbeat = decode_heartbeat(payload, allowed_bot_ids=self.allowed_bot_ids)
        except HeartbeatValidationError:
            return False
        return await self.store.accept_heartbeat(heartbeat.bot_id, heartbeat)
