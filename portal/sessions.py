"""Bounded, opaque, server-side browser sessions."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol


@dataclass(frozen=True, slots=True)
class PortalSession:
    session_id: str
    csrf_token: str
    identity_id: str | None
    created_at: datetime
    last_seen_at: datetime
    absolute_expires_at: datetime


class SessionStore(Protocol):
    def create(self, identity_id: str | None = None) -> PortalSession: ...
    def get(self, session_id: str) -> PortalSession | None: ...
    def rotate(self, session_id: str, identity_id: str) -> PortalSession: ...
    def invalidate(self, session_id: str) -> None: ...
    def cleanup(self) -> int: ...


class MemorySessionStore:
    def __init__(self, *, idle_timeout: timedelta = timedelta(minutes=30), absolute_timeout: timedelta = timedelta(hours=8), max_sessions: int = 1024, clock: Callable[[], datetime] | None = None) -> None:
        self.idle_timeout = idle_timeout
        self.absolute_timeout = absolute_timeout
        self.max_sessions = max_sessions
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sessions: dict[str, PortalSession] = {}

    def create(self, identity_id: str | None = None) -> PortalSession:
        self.cleanup()
        while len(self._sessions) >= self.max_sessions:
            oldest = min(self._sessions.values(), key=lambda item: item.last_seen_at)
            self._sessions.pop(oldest.session_id, None)
        now = self._clock()
        session = PortalSession(secrets.token_urlsafe(32), secrets.token_urlsafe(32), identity_id, now, now, now + self.absolute_timeout)
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> PortalSession | None:
        session = self._sessions.get(session_id)
        now = self._clock()
        if session is None:
            return None
        if now >= session.absolute_expires_at or now - session.last_seen_at >= self.idle_timeout:
            self._sessions.pop(session_id, None)
            return None
        touched = PortalSession(session.session_id, session.csrf_token, session.identity_id, session.created_at, now, session.absolute_expires_at)
        self._sessions[session_id] = touched
        return touched

    def rotate(self, session_id: str, identity_id: str) -> PortalSession:
        self.invalidate(session_id)
        return self.create(identity_id)

    def invalidate(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def cleanup(self) -> int:
        before = len(self._sessions)
        now = self._clock()
        self._sessions = {key: value for key, value in self._sessions.items() if now < value.absolute_expires_at and now - value.last_seen_at < self.idle_timeout}
        return before - len(self._sessions)
