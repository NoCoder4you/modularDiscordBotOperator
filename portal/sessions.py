"""Bounded, opaque, server-side browser sessions."""

from __future__ import annotations

import secrets
import hashlib
import sqlite3
import threading
from pathlib import Path
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
    session_revision: int = 0


class SessionStore(Protocol):
    def create(self, identity_id: str | None = None, session_revision: int = 0) -> PortalSession: ...
    def get(self, session_id: str) -> PortalSession | None: ...
    def rotate(self, session_id: str, identity_id: str, session_revision: int = 0) -> PortalSession: ...
    def invalidate(self, session_id: str) -> None: ...
    def cleanup(self) -> int: ...
    def invalidate_identity(self, identity_id: str) -> int: ...


class MemorySessionStore:
    def __init__(self, *, idle_timeout: timedelta = timedelta(minutes=30), absolute_timeout: timedelta = timedelta(hours=8), max_sessions: int = 1024, clock: Callable[[], datetime] | None = None) -> None:
        self.idle_timeout = idle_timeout
        self.absolute_timeout = absolute_timeout
        self.max_sessions = max_sessions
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sessions: dict[str, PortalSession] = {}

    def create(self, identity_id: str | None = None, session_revision: int = 0) -> PortalSession:
        self.cleanup()
        while len(self._sessions) >= self.max_sessions:
            oldest = min(self._sessions.values(), key=lambda item: item.last_seen_at)
            self._sessions.pop(oldest.session_id, None)
        now = self._clock()
        session = PortalSession(secrets.token_urlsafe(32), secrets.token_urlsafe(32), identity_id, now, now, now + self.absolute_timeout, session_revision)
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
        touched = PortalSession(session.session_id, session.csrf_token, session.identity_id, session.created_at, now, session.absolute_expires_at, session.session_revision)
        self._sessions[session_id] = touched
        return touched

    def rotate(self, session_id: str, identity_id: str, session_revision: int = 0) -> PortalSession:
        self.invalidate(session_id)
        return self.create(identity_id, session_revision)

    def invalidate(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def cleanup(self) -> int:
        before = len(self._sessions)
        now = self._clock()
        self._sessions = {key: value for key, value in self._sessions.items() if now < value.absolute_expires_at and now - value.last_seen_at < self.idle_timeout}
        return before - len(self._sessions)

    def invalidate_identity(self, identity_id: str) -> int:
        keys = [key for key, value in self._sessions.items() if value.identity_id == identity_id]
        for key in keys:
            self._sessions.pop(key, None)
        return len(keys)


class SQLiteSessionStore:
    """Restart-safe sessions; only SHA-256 token digests are persisted."""

    def __init__(self, path: Path, *, idle_timeout: timedelta = timedelta(minutes=30), absolute_timeout: timedelta = timedelta(hours=8), max_sessions: int = 1024, clock: Callable[[], datetime] | None = None) -> None:
        self.path, self.idle_timeout, self.absolute_timeout = Path(path), idle_timeout, absolute_timeout
        self.max_sessions, self._clock, self._lock = max_sessions, clock or (lambda: datetime.now(timezone.utc)), threading.RLock()

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def create(self, identity_id: str | None = None, session_revision: int = 0) -> PortalSession:
        with self._lock:
            self.cleanup()
            now = self._clock()
            token = secrets.token_urlsafe(32)
            item = PortalSession(token, secrets.token_urlsafe(32), identity_id, now, now, now + self.absolute_timeout, session_revision)
            with self._connect() as db:
                count = db.execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0]
                if count >= self.max_sessions:
                    db.execute("DELETE FROM portal_sessions WHERE token_digest=(SELECT token_digest FROM portal_sessions ORDER BY last_seen_at LIMIT 1)")
                db.execute("INSERT INTO portal_sessions VALUES (?,?,?,?,?,?,?)", (self._digest(token), item.csrf_token, identity_id, session_revision, now.isoformat(), now.isoformat(), item.absolute_expires_at.isoformat()))
            return item

    def get(self, session_id: str) -> PortalSession | None:
        with self._lock, self._connect() as db:
            digest, now = self._digest(session_id), self._clock()
            row = db.execute("SELECT * FROM portal_sessions WHERE token_digest=?", (digest,)).fetchone()
            if row is None:
                return None
            created, seen, absolute = (datetime.fromisoformat(row[key]) for key in ("created_at", "last_seen_at", "absolute_expires_at"))
            if now >= absolute or now - seen >= self.idle_timeout:
                db.execute("DELETE FROM portal_sessions WHERE token_digest=?", (digest,))
                return None
            db.execute("UPDATE portal_sessions SET last_seen_at=? WHERE token_digest=?", (now.isoformat(), digest))
            return PortalSession(session_id, row["csrf_token"], row["identity_id"], created, now, absolute, int(row["session_revision"]))

    def rotate(self, session_id: str, identity_id: str, session_revision: int = 0) -> PortalSession:
        self.invalidate(session_id)
        return self.create(identity_id, session_revision)

    def invalidate(self, session_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM portal_sessions WHERE token_digest=?", (self._digest(session_id),))

    def invalidate_identity(self, identity_id: str) -> int:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM portal_sessions WHERE identity_id=?", (identity_id,))
            return cursor.rowcount

    def cleanup(self) -> int:
        now, idle_cutoff = self._clock(), self._clock() - self.idle_timeout
        with self._connect() as db:
            cursor = db.execute("DELETE FROM portal_sessions WHERE absolute_expires_at<=? OR last_seen_at<=?", (now.isoformat(), idle_cutoff.isoformat()))
            return cursor.rowcount
