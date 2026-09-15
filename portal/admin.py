"""Narrow, shell-operator CLI for portal identity data only."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .identity import CANONICAL_BOT_IDS, SQLiteIdentityStore, hash_password
from .management import DenyByDefaultAuthorizer


def _password() -> str:
    first = getpass.getpass("New portal password: ")
    if first != getpass.getpass("Confirm portal password: "):
        raise ValueError("passwords do not match")
    return first


def _audit(name: str, target: str, operation_id: str, *, result: str, permission: str | None = None, bot_id: str | None = None) -> None:
    event = {"event": name, "timestamp": datetime.now(timezone.utc).isoformat(), "operation_id": operation_id, "actor": f"local-operator:{getpass.getuser()}", "target_identity_id": target, "result": result}
    if permission is not None:
        event["permission"] = permission
    if bot_id is not None:
        event["bot_id"] = bot_id
    print(json.dumps(event, sort_keys=True), file=sys.stderr)


def _identity(store: SQLiteIdentityStore, value: str):
    identity = store.find_by_id(value) or store.find_by_login(value)
    if identity is None:
        raise ValueError("identity not found")
    return identity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="portal-admin", description="Administer portal identities (never bots or processes)")
    parser.add_argument("--database", type=Path, default=Path(os.environ.get("MDBO_PORTAL_DATABASE", "runtime/data/portal/identities.sqlite3")))
    groups = parser.add_subparsers(dest="group", required=True)
    identities = groups.add_parser("identities").add_subparsers(dest="action", required=True)
    identities.add_parser("list")
    create = identities.add_parser("create")
    create.add_argument("login")
    create.add_argument("--administrator", action="store_true")
    for action in ("password", "enable", "disable", "promote", "demote", "show"):
        command = identities.add_parser(action)
        command.add_argument("identity")
    permissions = groups.add_parser("permissions").add_subparsers(dest="action", required=True)
    permissions.add_parser("catalog")
    for action in ("grant", "revoke"):
        command = permissions.add_parser(action)
        command.add_argument("identity")
        command.add_argument("permission", choices=sorted(DenyByDefaultAuthorizer.KNOWN_PERMISSIONS))
    bots = groups.add_parser("bots").add_subparsers(dest="action", required=True)
    for action in ("restrict", "unrestrict"):
        command = bots.add_parser(action)
        command.add_argument("identity")
        command.add_argument("bot_id", choices=sorted(CANONICAL_BOT_IDS))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    operation_id = str(uuid.uuid4())
    try:
        store = SQLiteIdentityStore(args.database)
        if args.group == "identities" and args.action == "list":
            for item in store.list_identities():
                print(json.dumps({"identity_id": item.identity_id, "login": item.login, "enabled": item.enabled, "administrator": item.administrator, "permissions": sorted(item.permissions), "bot_ids": None if item.bot_ids is None else sorted(item.bot_ids), "created_at": item.created_at.isoformat(), "last_login_at": None if item.last_login_at is None else item.last_login_at.isoformat()}, sort_keys=True))
            return 0
        if args.group == "permissions" and args.action == "catalog":
            print("\n".join(sorted(DenyByDefaultAuthorizer.KNOWN_PERMISSIONS)))
            return 0
        if args.group == "identities" and args.action == "create":
            item = store.create(args.login, hash_password(_password()), frozenset(), None, administrator=args.administrator)
            _audit("portal.identity.created", item.identity_id, operation_id, result="succeeded")
            print(f"Created portal identity {item.identity_id} for {item.login}")
            return 0
        item = _identity(store, args.identity)
        event, extra = "", {}
        if args.group == "identities":
            if args.action == "show":
                print(json.dumps({"identity_id": item.identity_id, "login": item.login, "enabled": item.enabled, "administrator": item.administrator, "permissions": sorted(item.permissions), "bot_ids": None if item.bot_ids is None else sorted(item.bot_ids)}, sort_keys=True))
                return 0
            if args.action == "password":
                store.admin_update(item.identity_id, password_hash=hash_password(_password()), expected_version=item.row_version)
                event = "portal.identity.password_changed"
            elif args.action in {"enable", "disable"}:
                store.admin_update(item.identity_id, enabled=args.action == "enable", expected_version=item.row_version)
                event = f"portal.identity.{args.action}d"
            else:
                store.admin_update(item.identity_id, administrator=args.action == "promote", expected_version=item.row_version)
                event = "portal.identity.admin_status_changed"
        elif args.group == "permissions":
            updated = set(item.permissions)
            getattr(updated, "add" if args.action == "grant" else "discard")(args.permission)
            store.admin_update(item.identity_id, permissions=frozenset(updated), expected_version=item.row_version)
            event, extra = f"portal.identity.permission_{args.action}ed", {"permission": args.permission}
        else:
            if args.action == "unrestrict":
                bot_ids = None
            else:
                bot_ids = frozenset({args.bot_id}) if item.bot_ids is None else item.bot_ids | {args.bot_id}
            store.admin_update(item.identity_id, bot_ids=bot_ids, expected_version=item.row_version)
            event, extra = "portal.identity.bot_restriction_changed", {"bot_id": args.bot_id}
        _audit(event, item.identity_id, operation_id, result="succeeded", **extra)
        _audit("portal.sessions.revoked", item.identity_id, operation_id, result="succeeded")
        print("Identity updated; active sessions revoked.")
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"portal-admin: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
