# Controlled identity administration (Stage 11)

`portal-admin` is a narrow local CLI. Its security boundary is OS shell access and database file
permissions; `local-operator:<unix-user>` is audit context, **not** browser authentication. It has no
shell, SQL, process, systemd, path-browser, supervisor, health, or bot-business command.

```console
portal-admin --database /var/lib/mdbo/portal/identities.sqlite3 identities list
portal-admin --database /var/lib/mdbo/portal/identities.sqlite3 identities create <login> --administrator
portal-admin --database /var/lib/mdbo/portal/identities.sqlite3 identities password <identity>
portal-admin --database /var/lib/mdbo/portal/identities.sqlite3 identities disable <identity>
portal-admin --database /var/lib/mdbo/portal/identities.sqlite3 identities enable <identity>
portal-admin --database /var/lib/mdbo/portal/identities.sqlite3 permissions grant <identity> bots.restart
portal-admin --database /var/lib/mdbo/portal/identities.sqlite3 permissions revoke <identity> bots.restart
portal-admin --database /var/lib/mdbo/portal/identities.sqlite3 bots restrict <identity> cda-admin
portal-admin --database /var/lib/mdbo/portal/identities.sqlite3 bots unrestrict <identity> cda-admin
```

Passwords are prompted twice without echo and never accepted in argv. Every sensitive update is a
locked transaction which increments `session_revision` and `row_version` and deletes that identity's
persistent sessions. Memory sessions are rejected on their next request by revision mismatch.
Password, enable/disable, permission, bot restriction, and administrator changes therefore require
fresh login. Re-enabling cannot restore a session. Optimistic row versions reject stale writes.
The last enabled administrator cannot be disabled or demoted.

The Stage 9 permission catalog and authorizer remain authoritative. Administrators receive every
catalog permission across every catalog bot; otherwise permissions are explicit and `bot_ids` is an
allow-list. There is no explicit-deny model. Per-bot restriction is applied after global permission.
Identity listings contain only IDs, login, state, administrator flag, safe permissions/restrictions,
and timestamps—never verifiers or session/CSRF material.

## Recovery

* Forgotten password: run `identities password` as the protected portal OS account.
* Disabled account: another enabled administrator may run `identities enable`; last-admin protection
  prevents the usual lockout case. There is no web recovery endpoint.
* Expired/revoked session: sign in again. For a corrupt session table, stop the portal, back up the
  database, delete only rows from `portal_sessions` using an approved maintenance procedure, and
  restart; identities remain authoritative.
* Failed migration: follow the backup/rollback procedure in `database-migrations.md`.
* Backup restore: restore the entire SQLite database with owner-only permissions while the portal is
  stopped. Restoring old sessions is risky; clear sessions before reopening access.
* Session secret rotation: tokens are random per-session and stored only as SHA-256 digests; clearing
  all session rows performs global rotation and forces login.
