# Management platform threat model

## Scope and assets

Future portal, supervisor, bot processes, local control/heartbeat/log channels, runtime data, backups, deployment releases, sessions, OAuth identity, and audit records are in scope. Assets are Discord/API secrets, authorization integrity, bot availability, pay/verification state, host integrity, and audit evidence. The browser, log text, bot IDs, filenames, JSON, archives, OAuth claims, and process/PID evidence are untrusted. Portal, supervisor, each bot OS account, systemd, and backup storage are separate trust boundaries.

## Prioritized threats and controls

| Priority | Threat / impact | Required controls and verification |
|---|---|---|
| BLOCKER | shell/command injection through bot action | no shell or command-string API; fixed manifest-derived argv; catalog membership; typed operations; hostile-ID tests |
| BLOCKER | path traversal, symlink/archive restore escape, cross-bot access | canonical ID, resource allow-list, dirfd/no-follow operations, reject absolute/`..`/symlinks/devices, archive extraction limits, separate Unix users and 0700 roots |
| BLOCKER | unauthorized controls/IDOR/privilege escalation | deny-default backend RBAC on every object/action, canonical per-bot scope, owner-only security/deploy/restore, second enforcement at supervisor boundary, audit tests |
| HIGH | secret leakage through portal, argv, environment dump, logs, exceptions, URLs or audit | systemd credentials/root-readable env file; minimal allow-listed environment; no secret read API; value/pattern redaction; safe error codes; fixtures/scans |
| HIGH | PID spoofing/reuse or stale PID file stops unrelated process | systemd named units/cgroups/invocation ID; PID + OS start time + instance heartbeat; PID files never authoritative; explicit reconciliation |
| HIGH | CSRF, session theft, Discord OAuth misuse | Secure/HttpOnly/SameSite cookies, state/nonce/PKCE, exact redirect allow-list, CSRF tokens for mutations, session rotation/short lifetime, server-side allow-list and revocation |
| HIGH | WebSocket authorization bypass/stale permission | authenticate handshake and reconnect, authorize bot/feature, periodic/revocation push checks, terminate immediately on role/session change, origin checks |
| HIGH | malformed/oversized JSON, logs, filenames or archive causes corruption/DoS | typed schemas, byte/depth/count limits, bounded buffers, escaped UI rendering, safe filename grammar, timeouts, quotas, backpressure |
| HIGH | race during config/data write, backup or restore | per-resource locks, optimistic versions, atomic fsync writes, quiesce/maintenance protocol, pre-change backup, checksums and rollback |
| HIGH | crash loop exhausts Discord/host resources | durable rolling counters, exponential capped backoff, latch/manual reset, systemd start limits, audit/alert |
| MEDIUM | log injection or terminal/browser escape | store stream and record boundaries, normalize controls for display, HTML escaping, never interpret ANSI by default, tag supervisor receipt time |
| MEDIUM | accidental cross-bot reads by portal/supervisor | no filesystem browsing; typed resource registry; least-privilege service users/groups; authorization tests per bot |
| MEDIUM | malicious deployment/release or partial update | signed/trusted origin where feasible, immutable staging, validation/checksums, atomic symlink, affected-unit restart, health gate and rollback |
| MEDIUM | audit tampering/replay/concurrent duplicate actions | append-only restricted store, operation/idempotency IDs, actor/session/time/result, database constraints, clock discipline, redacted metadata |
| MEDIUM | power loss corrupts JSON/SQLite | atomic replace+directory fsync, SQLite WAL/checkpoint policy if adopted, tested restore, external backups/UPS |

## Abuse cases

* `../../rpa-admin`, encoded separators, mixed-case aliases, shell metacharacters, and valid-but-unregistered IDs are rejected before lookup.
* An operator with `bots.restart` for UNBOT cannot alter `bot_id` to restart CDA Pay, read its logs, or restore its data.
* A malicious log line cannot create HTML, forge an audit event, grow memory without bound, or reveal a token supplied in environment.
* A stale heartbeat/PID cannot prove ownership after supervisor or host restart.
* A backup containing `../`, absolute paths, symlinks, hard links, device nodes, huge expansion, or duplicate normalized names is rejected in staging.

## Security acceptance gates

Before privileged portal controls: threat-focused unit/integration tests, session/CSRF/OAuth review, permission matrix tests, secret scan, dependency audit, file permission inspection, hostile path/archive suite, process identity/PID reuse test, log redaction/bounds tests, WebSocket revocation test, and restore/deploy rollback drill. Production processes must not run as root.
