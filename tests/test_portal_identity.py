from __future__ import annotations

from datetime import datetime, timedelta, timezone

from portal.identity import PortalAuthenticator, SQLiteIdentityStore, hash_password, verify_password
from portal.sessions import MemorySessionStore


def test_sqlite_identity_password_and_fresh_metadata(tmp_path):
    store = SQLiteIdentityStore(tmp_path / "runtime" / "identities.sqlite3")
    encoded = hash_password("fixture-password-123")
    identity = store.create("operator", encoded, frozenset({"bots.view"}), frozenset({"unbot"}))
    raw = (tmp_path / "runtime" / "identities.sqlite3").read_bytes()
    assert b"fixture-password-123" not in raw
    assert identity.password_hash != "fixture-password-123"
    assert verify_password("fixture-password-123", encoded)
    assert not verify_password("incorrect-password", encoded)
    authenticated = PortalAuthenticator(store).authenticate("operator", "fixture-password-123")
    assert authenticated is not None
    assert store.find_by_id(identity.identity_id).last_login_at is not None
    assert PortalAuthenticator(store).authenticate("unknown", "incorrect-password") is None
    store.set_enabled(identity.identity_id, False)
    assert PortalAuthenticator(store).authenticate("operator", "fixture-password-123") is None


def test_sessions_are_opaque_rotated_expiring_and_bounded():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def clock():
        return now
    sessions = MemorySessionStore(idle_timeout=timedelta(minutes=5), max_sessions=2, clock=clock)
    anonymous = sessions.create()
    assert len(anonymous.session_id) >= 40 and anonymous.session_id != anonymous.csrf_token
    authenticated = sessions.rotate(anonymous.session_id, "identity-1")
    assert sessions.get(anonymous.session_id) is None
    assert sessions.get(authenticated.session_id).identity_id == "identity-1"
    sessions.invalidate(authenticated.session_id)
    assert sessions.get(authenticated.session_id) is None
    sessions.create()
    sessions.create()
    sessions.create()
    assert len(sessions._sessions) == 2


def test_session_expiry_cleanup():
    current = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    sessions = MemorySessionStore(idle_timeout=timedelta(seconds=2), clock=lambda: current[0])
    item = sessions.create()
    current[0] += timedelta(seconds=3)
    assert sessions.get(item.session_id) is None
    assert sessions.cleanup() == 0
