"""Explicit operator-controlled initial identity bootstrap command."""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from .identity import SQLiteIdentityStore, hash_password
from .management import DenyByDefaultAuthorizer


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local portal identity")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--login", required=True)
    parser.add_argument("--permission", action="append", default=[])
    parser.add_argument("--bot", action="append", default=None)
    args = parser.parse_args()
    permissions = frozenset(args.permission)
    unknown = permissions - DenyByDefaultAuthorizer.KNOWN_PERMISSIONS
    if unknown:
        parser.error("unknown permission supplied")
    password = getpass.getpass("New portal password: ")
    confirmation = getpass.getpass("Confirm portal password: ")
    if password != confirmation:
        parser.error("passwords do not match")
    store = SQLiteIdentityStore(args.database)
    identity = store.create(args.login, hash_password(password), permissions, None if args.bot is None else frozenset(args.bot))
    print(f"Created portal identity {identity.identity_id} for {identity.login}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
