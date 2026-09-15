# Stage 10 local identity and minimal portal

## Architecture and scope

The browser-facing transport is a thin server-rendered layer over
`ManagementApplication`, the Stage 9 application boundary. It maps a current local identity to the
existing Stage 9 `Principal`, uses `DenyByDefaultAuthorizer`, and delegates catalog, canonical
health, lifecycle, and operation queries. It does not import or call `SupervisorService`,
`HealthStore`, systemd, subprocess, Discord, bot packages, or filesystem helpers. Stage 7 operation
IDs/serialization and Stage 8 canonical states remain authoritative. There is no portal-side health
calculation and lifecycle HTTP requests do not wait for Discord READY.

Stage 10 deliberately adds no Discord OAuth, Discord account login, user-management UI, CORS,
WebSockets, arbitrary command/unit/path input, logs, terminal, configuration editing, or deployment
automation. Discord bot tokens and the Stage 9 management bearer credential are never human login
credentials.

## Local identities and bootstrap

`IdentityStore` is the replaceable contract. `SQLiteIdentityStore` is the local implementation and
uses schema initialization, uniqueness/integrity constraints, transactions, and parameterized SQL.
Records contain a UUID identity ID, case-insensitive login, enabled flag, password verifier,
permissions, optional bot allow-list, and created/updated/last-login timestamps. Routes receive only
the typed domain record—not SQLite rows.

Passwords use salted `hashlib.scrypt` (N=16384, r=8, p=1) with an OS-generated 128-bit salt. They
are neither reversibly encrypted nor logged. Verification is constant-time after derivation and an
unknown login performs a dummy derivation to reduce enumeration signals. Responses never include a
verifier.

There is no default identity or password. An operator creates one explicitly while logged in as the
portal Unix user:

```console
python -m portal.bootstrap --database /var/lib/mdbo/portal/identities.sqlite3 \
  --login operator --permission bots.view --permission bots.restart \
  --permission operations.view --bot cda-admin
```

The command prompts twice without echo. Repeat `--permission` and `--bot` as needed; omitting
`--bot` permits the explicitly granted permissions across registered bots. The runtime directory
must be mode `0700`, the database mode `0600`, owned by the dedicated portal Unix user, and backed
up according to local policy. The database belongs under the runtime data root and is git-ignored.

## Sessions, login, logout, and authorization freshness

`SessionStore` is replaceable. Stage 10's bounded in-process implementation stores all state on the
server and gives the browser only a 256-bit, URL-safe, opaque identifier produced by `secrets`.
Separate 256-bit synchronizer tokens are generated per session. Defaults are a 30-minute idle limit,
an eight-hour absolute limit, and 1,024 live sessions. Lookup performs deterministic expiry;
creation performs cleanup and evicts the least recently used session at the bound. No scheduler is
required.

GET `/portal/login` creates an anonymous session and CSRF token. Successful password verification
invalidates that identifier and creates an authenticated one, preventing fixation; last-login is
updated and `portal.login.succeeded` is audited. Failure is generic and emits
`portal.login.failed`, without login/password data. POST `/portal/logout` verifies CSRF, invalidates
server state, expires the cookie, and emits `portal.logout`. Logout is not available via GET.

The cookie is `HttpOnly`, `SameSite=Strict`, path-scoped to `/portal`, bounded to eight hours, and
`Secure` by default. Tests may explicitly disable `Secure` for HTTP-only ASGI clients. Production
must not do so.

Sessions retain only `identity_id`, never permissions. Every protected request reloads the identity;
a disabled/deleted identity immediately loses access and its encountered session is invalidated.
The newly loaded identity becomes a Stage 9 `Principal`, so permission and per-bot changes take
effect on the next request. Authentication never implies authorization. Lifecycle visibility is
only a convenience; `ManagementApplication` enforces the same server-side action permission.

## CSRF, views, and browser security

Synchronizer-token checks protect POST login, logout, start, stop, and restart. Tokens are tied to
one server session and compared in constant time. Missing, incorrect, cross-session, or expired
tokens fail. If an `Origin` header is present it must match the request origin; SameSite is defense
in depth, not the CSRF mechanism. Forms accept only URL-encoded bodies up to 4 KiB. There are no
uploads or state-changing GET routes. Login return locations are restricted to absolute local
`/portal/` paths, preventing external and scheme-relative redirects.

The bot list comes from Stage 9 and includes only `bots.view`-authorized entries. Bot detail renders
the Stage 8-derived state and safe heartbeat/Discord booleans. Controls call Stage 9 asynchronously
and redirect to the preserved operation ID. Operation pages show only ID, bot, action, status, and
safe timestamps—never process details, paths, argv, environment, unit names, or exceptions.

All HTML values are escaped. Portal pages send `no-store`, request IDs, `nosniff`, no-referrer,
deny-framing, and a restrictive CSP with no `unsafe-eval` or `unsafe-inline`. CORS remains disabled.
Errors render bounded safe messages and request IDs. Login attempts use the existing local sliding
window limiter design; lifecycle attempts use Stage 9's per-principal/per-bot limiter. Audit objects
contain bounded IDs/actions/results and never passwords, hashes, session IDs, or CSRF tokens.

## Deployment assumptions

The supported topology is browser -> HTTPS reverse proxy -> portal bound to `127.0.0.1` or a
permissioned Unix socket -> Stage 9 application -> supervisor/health core. TLS is mandatory for
production. Run under a dedicated least-privilege Unix account, keep identity data beneath a
protected runtime root, and supply non-identity secrets using the existing external secret
facility. Do not blindly trust forwarded headers; only a deliberately configured trusted proxy may
set them. Stage 10 makes no reverse-proxy, systemd, firewall, DNS, account, or production-process
changes.
