"""Small, optional heartbeat client shared by all bot processes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final
from uuid import UUID

SCHEMA_VERSION: Final = 1
MAX_HEARTBEAT_BYTES: Final = 2048
DEFAULT_CADENCE_SECONDS: Final = 10.0


@dataclass(frozen=True, slots=True)
class Heartbeat:
    schema_version: int
    bot_id: str
    process_instance_id: str
    sequence: int
    emitted_at: datetime
    discord_connected: bool
    discord_ready: bool
    maintenance: bool

    def encode(self) -> bytes:
        payload = asdict(self)
        payload["emitted_at"] = self.emitted_at.isoformat()
        return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


class HeartbeatValidationError(ValueError):
    pass


def decode_heartbeat(payload: bytes, *, allowed_bot_ids: frozenset[str]) -> Heartbeat:
    if len(payload) > MAX_HEARTBEAT_BYTES:
        raise HeartbeatValidationError("heartbeat exceeds size limit")
    try:
        raw = json.loads(payload)
        expected = {f.name for f in Heartbeat.__dataclass_fields__.values()}
        if not isinstance(raw, dict) or set(raw) != expected:
            raise HeartbeatValidationError("heartbeat fields are invalid")
        if raw["schema_version"] != SCHEMA_VERSION:
            raise HeartbeatValidationError("unsupported heartbeat version")
        if raw["bot_id"] not in allowed_bot_ids:
            raise HeartbeatValidationError("unknown bot ID")
        instance = str(UUID(raw["process_instance_id"]))
        emitted = datetime.fromisoformat(raw["emitted_at"])
        if emitted.tzinfo is None or emitted.utcoffset() is None:
            raise HeartbeatValidationError("timestamp must be timezone-aware")
        if type(raw["sequence"]) is not int or raw["sequence"] < 0:
            raise HeartbeatValidationError("sequence is invalid")
        for name in ("discord_connected", "discord_ready", "maintenance"):
            if type(raw[name]) is not bool:
                raise HeartbeatValidationError(f"{name} is invalid")
        if raw["discord_ready"] and not raw["discord_connected"]:
            raise HeartbeatValidationError("READY requires a connection")
        return Heartbeat(
            SCHEMA_VERSION,
            raw["bot_id"],
            instance,
            raw["sequence"],
            emitted,
            raw["discord_connected"],
            raw["discord_ready"],
            raw["maintenance"],
        )
    except HeartbeatValidationError:
        raise
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise HeartbeatValidationError("malformed heartbeat") from exc


class HeartbeatReporter:
    """Non-blocking best-effort Unix datagram reporter with bounded log noise."""

    def __init__(
        self,
        bot_id: str,
        *,
        socket_path: Path | None = None,
        process_instance_id: str | None = None,
        cadence: float = DEFAULT_CADENCE_SECONDS,
        logger: logging.Logger | None = None,
    ) -> None:
        self.bot_id = bot_id
        self.socket_path = socket_path or (
            Path(os.environ["MDBO_HEARTBEAT_SOCKET"])
            if os.environ.get("MDBO_HEARTBEAT_SOCKET")
            else None
        )
        self.process_instance_id = process_instance_id or os.environ.get("MDBO_PROCESS_INSTANCE_ID")
        self.cadence = cadence
        self.logger = logger or logging.getLogger(__name__)
        self.connected = False
        self.ready = False
        self.maintenance = False
        self._sequence = 0
        self._task: asyncio.Task[None] | None = None
        self._failure_logged = False

    @property
    def enabled(self) -> bool:
        if self.socket_path is None or self.process_instance_id is None:
            return False
        try:
            UUID(self.process_instance_id)
            return True
        except ValueError:
            return False

    def attach(self, client: object) -> None:
        """Attach generic discord.py listeners without owning business tasks."""
        add_listener = getattr(client, "add_listener")
        add_listener(self.on_connect, "on_connect")
        add_listener(self.on_ready, "on_ready")
        add_listener(self.on_disconnect, "on_disconnect")

    async def on_connect(self) -> None:
        self.connected = True
        self.ready = False
        self.start()

    async def on_ready(self) -> None:
        self.connected = True
        self.ready = True
        self.start()

    async def on_disconnect(self) -> None:
        self.connected = False
        self.ready = False
        await self.emit()

    def start(self) -> None:
        if self.enabled and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._run(), name=f"heartbeat:{self.bot_id}")

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            await self.emit()
            await asyncio.sleep(self.cadence)

    async def emit(self) -> bool:
        if not self.enabled:
            return False
        heartbeat = Heartbeat(
            SCHEMA_VERSION,
            self.bot_id,
            self.process_instance_id or "",
            self._sequence,
            datetime.now(timezone.utc),
            self.connected,
            self.ready,
            self.maintenance,
        )
        self._sequence += 1
        try:
            await asyncio.to_thread(self._send, heartbeat.encode())
            if self._failure_logged:
                self.logger.info("Heartbeat receiver recovered")
            self._failure_logged = False
            return True
        except (OSError, ValueError):
            if not self._failure_logged:
                self.logger.warning("Heartbeat receiver unavailable; Discord operation continues")
                self._failure_logged = True
            return False

    def _send(self, payload: bytes) -> None:
        if len(payload) > MAX_HEARTBEAT_BYTES:
            raise ValueError("heartbeat too large")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
            channel.settimeout(0.25)
            channel.sendto(payload, str(self.socket_path))
