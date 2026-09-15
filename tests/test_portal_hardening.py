from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import portal.identity as identity_module
from portal.admin import main
from portal.identity import IdentityMigrationError, SQLiteIdentityStore, hash_password, verify_password
from portal.sessions import MemorySessionStore, SQLiteSessionStore


def test_fresh_migration_is_ordered_current_and_idempotent(tmp_path):
    path = tmp_path / "portal.sqlite3"
    store = SQLiteIdentityStore(path)
    assert store.schema_version() == identity_module.LATEST_SCHEMA_VERSION
    before = path.stat().st_mtime_ns
    SQLiteIdentityStore(path)
    assert path.stat().st_mtime_ns == before


def test_stage10_upgrade_preserves_identity(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE portal_identities (identity_id TEXT PRIMARY KEY, login TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), permissions TEXT NOT NULL, bot_ids TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login_at TEXT)""")
        db.execute("INSERT INTO portal_identities VALUES ('id','operator','verifier',1,'[\"bots.view\"]',NULL,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00',NULL)")
    store = SQLiteIdentityStore(path)
    assert store.find_by_login("operator").session_revision == 0
    assert store.schema_version() == 3


def test_failed_migration_rolls_back_and_future_schema_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "failed.sqlite3"
    migrations = identity_module.MIGRATIONS
    def fail(db):
        db.execute("CREATE TABLE partial(value TEXT)")
        raise sqlite3.OperationalError("synthetic sensitive path")
    monkeypatch.setattr(identity_module, "MIGRATIONS", ((1, "001_failure", fail),))
    with __import__("pytest").raises(IdentityMigrationError, match="rolled back"):
        SQLiteIdentityStore(path)
    with sqlite3.connect(path) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='partial'").fetchone()
    monkeypatch.setattr(identity_module, "MIGRATIONS", migrations)

    future = tmp_path / "future.sqlite3"
    store = SQLiteIdentityStore(future)
    with store._connect() as db:
        db.execute("UPDATE portal_schema_version SET version=999")
    with __import__("pytest").raises(IdentityMigrationError, match="newer than supported"):
        SQLiteIdentityStore(future)


def test_concurrent_initialization(tmp_path):
    path = tmp_path / "race.sqlite3"
    with ThreadPoolExecutor(max_workers=4) as pool:
        stores = list(pool.map(lambda _: SQLiteIdentityStore(path), range(4)))
    assert {store.schema_version() for store in stores} == {3}


def test_security_update_revises_and_revokes_persistent_sessions(tmp_path):
    path = tmp_path / "portal.sqlite3"
    store = SQLiteIdentityStore(path)
    item = store.create("operator", hash_password("old-password-123"), frozenset({"bots.view"}), None, administrator=True)
    sessions = SQLiteSessionStore(path)
    session = sessions.create(item.identity_id, item.session_revision)
    updated = store.admin_update(item.identity_id, password_hash=hash_password("new-password-123"), expected_version=item.row_version)
    assert updated.session_revision == 1 and updated.row_version == 1
    assert sessions.get(session.session_id) is None
    assert not verify_password("old-password-123", updated.password_hash)
    assert verify_password("new-password-123", updated.password_hash)


def test_persistent_session_restart_digest_expiry_and_bounding(tmp_path):
    path = tmp_path / "portal.sqlite3"
    SQLiteIdentityStore(path)
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    first = SQLiteSessionStore(path, max_sessions=2, idle_timeout=timedelta(seconds=2), clock=lambda: now[0])
    session = first.create()
    raw = path.read_bytes()
    assert session.session_id.encode() not in raw
    assert SQLiteSessionStore(path, clock=lambda: now[0]).get(session.session_id) is not None
    first.create()
    first.create()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM portal_sessions").fetchone()[0] == 2
    now[0] += timedelta(seconds=3)
    assert first.cleanup() == 2


def test_admin_listing_and_permission_changes_are_safe(tmp_path, capsys, monkeypatch):
    path = tmp_path / "portal.sqlite3"
    store = SQLiteIdentityStore(path)
    item = store.create("operator", hash_password("fixture-password-123"), frozenset({"bots.view"}), None, administrator=True)
    assert main(["--database", str(path), "identities", "list"]) == 0
    output = capsys.readouterr().out
    assert "operator" in output
    assert "password_hash" not in output and "fixture-password" not in output and "csrf" not in output and "session_id" not in output
    assert main(["--database", str(path), "permissions", "grant", item.identity_id, "bots.restart"]) == 0
    captured = capsys.readouterr()
    event = captured.err
    assert "permission_granted" in event and "password" not in event and "session_id" not in event
    assert "bots.restart" in store.find_by_id(item.identity_id).permissions


def test_last_admin_and_invalid_catalog_values_fail_closed(tmp_path):
    store = SQLiteIdentityStore(tmp_path / "portal.sqlite3")
    admin = store.create("admin", hash_password("fixture-password-123"), frozenset(), None, administrator=True)
    with __import__("pytest").raises(ValueError, match="last enabled administrator"):
        store.admin_update(admin.identity_id, enabled=False)
    with __import__("pytest").raises(ValueError, match="unknown permission"):
        store.admin_update(admin.identity_id, permissions=frozenset({"root.everything"}))
    with __import__("pytest").raises(ValueError, match="unknown bot"):
        store.admin_update(admin.identity_id, bot_ids=frozenset({"../../unit"}))


def test_memory_store_revision_contract():
    sessions = MemorySessionStore()
    item = sessions.create("identity", 7)
    assert sessions.get(item.session_id).session_revision == 7
    assert sessions.invalidate_identity("identity") == 1
