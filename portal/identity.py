"""Replaceable local portal identities and password authentication."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .management import Principal

SCRYPT_N = 2**14


@dataclass(frozen=True, slots=True)
class PortalIdentity:
    identity_id: str
    login: str
    password_hash: str
    enabled: bool
    permissions: frozenset[str]
    bot_ids: frozenset[str] | None
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None

    def principal(self) -> Principal:
        return Principal(self.identity_id, self.permissions, self.bot_ids)


class IdentityStore(Protocol):
    def find_by_login(self, login: str) -> PortalIdentity | None: ...
    def find_by_id(self, identity_id: str) -> PortalIdentity | None: ...
    def create(self, login: str, password_hash: str, permissions: frozenset[str], bot_ids: frozenset[str] | None) -> PortalIdentity: ...
    def record_login(self, identity_id: str, at: datetime) -> None: ...
    def set_enabled(self, identity_id: str, enabled: bool) -> None: ...


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=8, p=1)
    return f"scrypt${SCRYPT_N}$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p)
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


class SQLiteIdentityStore:
    """SQLite identity adapter; the database belongs in a protected runtime directory."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS portal_identities (
                identity_id TEXT PRIMARY KEY, login TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                permissions TEXT NOT NULL, bot_ids TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, last_login_at TEXT)"""
            )
        os.chmod(self.path, 0o600)

    @staticmethod
    def _identity(row: sqlite3.Row) -> PortalIdentity:
        return PortalIdentity(
            row["identity_id"], row["login"], row["password_hash"], bool(row["enabled"]),
            frozenset(json.loads(row["permissions"])),
            None if row["bot_ids"] is None else frozenset(json.loads(row["bot_ids"])),
            datetime.fromisoformat(row["created_at"]), datetime.fromisoformat(row["updated_at"]),
            None if row["last_login_at"] is None else datetime.fromisoformat(row["last_login_at"]),
        )

    def find_by_login(self, login: str) -> PortalIdentity | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM portal_identities WHERE login = ?", (login,)).fetchone()
        return None if row is None else self._identity(row)

    def find_by_id(self, identity_id: str) -> PortalIdentity | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM portal_identities WHERE identity_id = ?", (identity_id,)).fetchone()
        return None if row is None else self._identity(row)

    def create(self, login: str, password_hash: str, permissions: frozenset[str], bot_ids: frozenset[str] | None) -> PortalIdentity:
        if not login or len(login) > 128:
            raise ValueError("login must contain 1 to 128 characters")
        now = datetime.now(timezone.utc)
        identity_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute(
                "INSERT INTO portal_identities VALUES (?, ?, ?, 1, ?, ?, ?, ?, NULL)",
                (identity_id, login, password_hash, json.dumps(sorted(permissions)),
                 None if bot_ids is None else json.dumps(sorted(bot_ids)), now.isoformat(), now.isoformat()),
            )
        identity = self.find_by_id(identity_id)
        assert identity is not None
        return identity

    def record_login(self, identity_id: str, at: datetime) -> None:
        with self._connect() as db:
            db.execute("UPDATE portal_identities SET last_login_at=?, updated_at=? WHERE identity_id=?", (at.isoformat(), at.isoformat(), identity_id))

    def set_enabled(self, identity_id: str, enabled: bool) -> None:
        with self._connect() as db:
            db.execute("UPDATE portal_identities SET enabled=?, updated_at=? WHERE identity_id=?", (int(enabled), datetime.now(timezone.utc).isoformat(), identity_id))


class PortalAuthenticator:
    """Password adapter which returns the existing Stage 9 Principal type."""

    # Valid work for an unknown account reduces practical timing-based enumeration.
    _dummy_hash = hash_password("not-a-real-password")

    def __init__(self, store: IdentityStore) -> None:
        self.store = store

    def authenticate(self, login: str, password: str) -> PortalIdentity | None:
        identity = self.store.find_by_login(login)
        encoded = identity.password_hash if identity else self._dummy_hash
        valid = verify_password(password, encoded)
        if not identity or not identity.enabled or not valid:
            return None
        self.store.record_login(identity.identity_id, datetime.now(timezone.utc))
        return identity
