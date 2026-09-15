"""Versioned local portal identities and controlled administration."""

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
from typing import Callable, Protocol

from .management import DenyByDefaultAuthorizer, Principal

SCRYPT_N = 2**14
CANONICAL_BOT_IDS = frozenset({"cda-admin", "cda-pay", "unbot", "rpa-admin"})
LATEST_SCHEMA_VERSION = 3


class IdentityMigrationError(RuntimeError):
    """Safe operator-facing migration failure."""


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
    session_revision: int = 0
    administrator: bool = False
    row_version: int = 0

    def principal(self) -> Principal:
        permissions = DenyByDefaultAuthorizer.KNOWN_PERMISSIONS if self.administrator else self.permissions
        return Principal(self.identity_id, permissions, None if self.administrator else self.bot_ids)


class IdentityStore(Protocol):
    def find_by_login(self, login: str) -> PortalIdentity | None: ...
    def find_by_id(self, identity_id: str) -> PortalIdentity | None: ...
    def create(self, login: str, password_hash: str, permissions: frozenset[str], bot_ids: frozenset[str] | None, *, administrator: bool = False) -> PortalIdentity: ...
    def record_login(self, identity_id: str, at: datetime) -> None: ...
    def set_enabled(self, identity_id: str, enabled: bool) -> None: ...


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 1024:
        raise ValueError("password must contain 12 to 1024 characters")
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=8, p=1)
    return f"scrypt${SCRYPT_N}$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def _migration_1(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE portal_identities (
        identity_id TEXT PRIMARY KEY, login TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
        permissions TEXT NOT NULL, bot_ids TEXT, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, last_login_at TEXT)""")


def _migration_2(db: sqlite3.Connection) -> None:
    db.execute("ALTER TABLE portal_identities ADD COLUMN session_revision INTEGER NOT NULL DEFAULT 0")
    db.execute("ALTER TABLE portal_identities ADD COLUMN administrator INTEGER NOT NULL DEFAULT 0 CHECK(administrator IN (0,1))")
    db.execute("ALTER TABLE portal_identities ADD COLUMN row_version INTEGER NOT NULL DEFAULT 0")


def _migration_3(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE portal_sessions (
        token_digest TEXT PRIMARY KEY, csrf_token TEXT NOT NULL, identity_id TEXT,
        session_revision INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL, absolute_expires_at TEXT NOT NULL,
        FOREIGN KEY(identity_id) REFERENCES portal_identities(identity_id) ON DELETE CASCADE)""")
    db.execute("CREATE INDEX portal_sessions_identity_idx ON portal_sessions(identity_id)")
    db.execute("CREATE INDEX portal_sessions_expiry_idx ON portal_sessions(absolute_expires_at)")


MIGRATIONS: tuple[tuple[int, str, Callable[[sqlite3.Connection], None]], ...] = (
    (1, "001_initial", _migration_1),
    (2, "002_identity_security_revision", _migration_2),
    (3, "003_persistent_sessions", _migration_3),
)


class SQLiteIdentityStore:
    """SQLite adapter with deterministic, transactional, lock-protected migrations."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.migrate()
        os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 30000")
        return db

    def schema_version(self) -> int:
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='portal_schema_version'").fetchone():
                return 0
            row = db.execute("SELECT version FROM portal_schema_version WHERE singleton=1").fetchone()
            return 0 if row is None else int(row[0])

    def migrate(self) -> None:
        db = self._connect()
        try:
            db.isolation_level = None
            db.execute("BEGIN IMMEDIATE")  # one writer serializes concurrent portal startup
            has_versions = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='portal_schema_version'").fetchone()
            has_legacy = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='portal_identities'").fetchone()
            db.execute("CREATE TABLE IF NOT EXISTS portal_schema_version (singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL, migration_name TEXT NOT NULL, applied_at TEXT NOT NULL)")
            row = db.execute("SELECT version FROM portal_schema_version WHERE singleton=1").fetchone()
            current = int(row[0]) if row else (1 if has_legacy and not has_versions else 0)
            if current > LATEST_SCHEMA_VERSION:
                raise IdentityMigrationError(f"identity schema version {current} is newer than supported version {LATEST_SCHEMA_VERSION}")
            for version, name, apply in MIGRATIONS:
                if version <= current:
                    continue
                apply(db)
                db.execute("INSERT INTO portal_schema_version VALUES (1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET version=excluded.version,migration_name=excluded.migration_name,applied_at=excluded.applied_at", (version, name, datetime.now(timezone.utc).isoformat()))
                current = version
            db.commit()
        except Exception as exc:
            db.rollback()
            if isinstance(exc, IdentityMigrationError):
                raise
            raise IdentityMigrationError("identity database migration failed; database was rolled back") from exc
        finally:
            db.close()

    @staticmethod
    def _identity(row: sqlite3.Row) -> PortalIdentity:
        return PortalIdentity(
            row["identity_id"], row["login"], row["password_hash"], bool(row["enabled"]),
            frozenset(json.loads(row["permissions"])), None if row["bot_ids"] is None else frozenset(json.loads(row["bot_ids"])),
            datetime.fromisoformat(row["created_at"]), datetime.fromisoformat(row["updated_at"]),
            None if row["last_login_at"] is None else datetime.fromisoformat(row["last_login_at"]),
            int(row["session_revision"]), bool(row["administrator"]), int(row["row_version"]),
        )

    def find_by_login(self, login: str) -> PortalIdentity | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM portal_identities WHERE login=?", (login,)).fetchone()
        return None if row is None else self._identity(row)

    def find_by_id(self, identity_id: str) -> PortalIdentity | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM portal_identities WHERE identity_id=?", (identity_id,)).fetchone()
        return None if row is None else self._identity(row)

    def list_identities(self) -> tuple[PortalIdentity, ...]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM portal_identities ORDER BY login COLLATE NOCASE").fetchall()
        return tuple(self._identity(row) for row in rows)

    def create(self, login: str, password_hash: str, permissions: frozenset[str], bot_ids: frozenset[str] | None, *, administrator: bool = False) -> PortalIdentity:
        self._validate(login, permissions, bot_ids)
        now, identity_id = datetime.now(timezone.utc).isoformat(), str(uuid.uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO portal_identities (identity_id,login,password_hash,enabled,permissions,bot_ids,created_at,updated_at,last_login_at,session_revision,administrator,row_version) VALUES (?,?,?,?,?,?,?,?,NULL,0,?,0)", (identity_id, login, password_hash, 1, json.dumps(sorted(permissions)), None if bot_ids is None else json.dumps(sorted(bot_ids)), now, now, int(administrator)))
        return self.find_by_id(identity_id)  # type: ignore[return-value]

    @staticmethod
    def _validate(login: str, permissions: frozenset[str], bot_ids: frozenset[str] | None) -> None:
        if not login or len(login) > 128 or any(ord(c) < 32 for c in login):
            raise ValueError("login must contain 1 to 128 printable characters")
        if permissions - DenyByDefaultAuthorizer.KNOWN_PERMISSIONS:
            raise ValueError("unknown permission")
        if bot_ids is not None and bot_ids - CANONICAL_BOT_IDS:
            raise ValueError("unknown bot")

    def record_login(self, identity_id: str, at: datetime) -> None:
        with self._connect() as db:
            db.execute("UPDATE portal_identities SET last_login_at=?,updated_at=? WHERE identity_id=?", (at.isoformat(), at.isoformat(), identity_id))

    def set_enabled(self, identity_id: str, enabled: bool) -> None:
        self.admin_update(identity_id, enabled=enabled)

    def admin_update(self, identity_id: str, *, password_hash: str | None = None, enabled: bool | None = None, permissions: frozenset[str] | None = None, bot_ids: frozenset[str] | None | object = ..., administrator: bool | None = None, expected_version: int | None = None) -> PortalIdentity:
        if permissions is not None or bot_ids is not ...:
            current = self.find_by_id(identity_id)
            if current is None:
                raise ValueError("identity not found")
            self._validate(current.login, current.permissions if permissions is None else permissions, current.bot_ids if bot_ids is ... else bot_ids)  # type: ignore[arg-type]
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM portal_identities WHERE identity_id=?", (identity_id,)).fetchone()
            if row is None:
                raise ValueError("identity not found")
            if expected_version is not None and int(row["row_version"]) != expected_version:
                raise RuntimeError("identity was concurrently modified")
            if (enabled is False or administrator is False) and bool(row["administrator"]):
                count = db.execute("SELECT COUNT(*) FROM portal_identities WHERE enabled=1 AND administrator=1").fetchone()[0]
                if count <= 1:
                    raise ValueError("cannot disable or demote the last enabled administrator")
            values = {
                "password_hash": row["password_hash"] if password_hash is None else password_hash,
                "enabled": row["enabled"] if enabled is None else int(enabled),
                "permissions": row["permissions"] if permissions is None else json.dumps(sorted(permissions)),
                "bot_ids": row["bot_ids"] if bot_ids is ... else (None if bot_ids is None else json.dumps(sorted(bot_ids))),
                "administrator": row["administrator"] if administrator is None else int(administrator),
            }
            now = datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE portal_identities SET password_hash=:password_hash,enabled=:enabled,permissions=:permissions,bot_ids=:bot_ids,administrator=:administrator,updated_at=:now,session_revision=session_revision+1,row_version=row_version+1 WHERE identity_id=:identity_id", {**values, "now": now, "identity_id": identity_id})
            db.execute("DELETE FROM portal_sessions WHERE identity_id=?", (identity_id,))
        return self.find_by_id(identity_id)  # type: ignore[return-value]


class PortalAuthenticator:
    _dummy_hash = hash_password("not-a-real-password")

    def __init__(self, store: IdentityStore) -> None:
        self.store = store

    def authenticate(self, login: str, password: str) -> PortalIdentity | None:
        identity = self.store.find_by_login(login)
        valid = verify_password(password, identity.password_hash if identity else self._dummy_hash)
        if not identity or not identity.enabled or not valid:
            return None
        self.store.record_login(identity.identity_id, datetime.now(timezone.utc))
        return identity
