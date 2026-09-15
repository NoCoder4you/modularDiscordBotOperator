# Stage 13 typed configuration and data management

## Decision and security boundary

Stage 13 extends the existing management composition; it does not replace the Stage 7 supervisor, Stage 8 health reconciler, Stage 9 principal/authorizer/audit boundary, Stage 10/11 session and CSRF controls, or Stage 12 typed bot-operation service. `DenyByDefaultAuthorizer` is authoritative. Every lookup checks permission, canonical bot ID, and stable resource ID. Authentication and bot assignment alone grant nothing; view does not imply edit, and `config.edit` never implies `bots.restart`.

Catalogs are closed mappings keyed by `(bot_id, resource_id)`. IDs use a bounded ASCII grammar and are never paths. Forms are generated from declared fields. Unknown fields, malformed Discord IDs, stale revisions, resources, and permissions fail closed. No CORS behavior was added.

## Canonical resource matrix

| bot | resource | kind | source / owner | schema | exposure | permission | revision / atomicity | runtime | sensitivity / backup | status |
|---|---|---|---|---|---|---|---|---|---|---|
| cda-admin | `channel-routing` | config | bot `server.json`; bot | four channel snowflakes | editable fields | `config.view/edit` | document SHA-256; lock + authorized atomic replace | restart reported only | internal / high | IMPLEMENTED |
| cda-admin | `verified-users` | data | bot `server.json`; bot | `user_id` only | read-only pages | `data.view` | document hash; locked snapshot | none | restricted / critical | READ-ONLY |
| cda-admin | roles/admins/punishment/codes/balances | mixed | bot JSON | implicit/mixed | none | — | mixed | unclear | security-critical | DEFERRED / NOT EXPOSED |
| cda-pay | routing/pay/voids/backups | mixed | bot JSON/tasks | implicit/time-partitioned | none | — | existing direct writes | unclear | payroll-critical | DEFERRED |
| unbot | tracker/snapshots/histories/presence | mixed | bot JSON/tasks | distributed | none | — | mixed concurrent writes | unclear | restricted | DEFERRED |
| rpa-admin | config/roles/verification/moderation/workflows | mixed | bot stores/tasks | distributed | none | — | store-specific | unclear | security-critical | DEFERRED |

Deferred resources require a bot-owned schema, coordination contract, proven invariants, and recovery tests. One safe real resource is preferable to treating JSON presence as eligibility.

## Persistence, concurrency, and recovery

The adapter receives an `AuthorizedPath` from trusted bootstrap, never the browser. It validates the document, writes a same-directory temporary file with restrictive `0600` mode, flushes/fsyncs, atomically replaces, and fsyncs the directory. POSIX descriptor traversal and no-follow reads refuse symlinks. A resource lock serializes local writers; a whole-document hash rejects external/concurrent changes. Revisions advance only after replacement. Failures leave the original intact and return `persistence_failed`. Malformed content is not rewritten and returns `resource_temporarily_unavailable`; repair/restore outside the portal, then reload. Stale edits must be reviewed again.

No SQLite bot resource or safe typed data mutation met eligibility, so neither is exposed. Future SQLite writes require transactions, row-version predicates, typed statements, and rollback tests. Backup/restore UI and hot reload are deferred. A restart during edit changes no persistence semantics: commit rechecks revision and never invokes `SupervisorService`.

## Views, preview, pagination, and audit

Same-origin pages list authorized entries only. Schema fields are revalidated at preview and confirmation; hidden values are not trusted. Structured diffs contain field IDs and safe old/new values; sensitive-field support emits `changed`. Mutation POSTs retain existing Origin, size, content-type, session, and CSRF checks. Data sorts by allow-listed `user_id`, defaults to 25, caps at 100, uses opaque cursors, and projects declared fields. No filters or alternate sorts exist.

Audit events carry actor, bot, resource, request ID, revisions, result, and changed field IDs—not values, paths, sessions, CSRF, environment, credentials, or exceptions. Errors are bounded typed codes.

## Explicit non-features

No filesystem paths/browser, raw JSON, upload, arbitrary SQL, shell, PTY, stdin, Python/eval/exec, subprocess/systemd interface, raw bot API, generic setter/editor, arbitrary registration, secret field, or bot-package import is exposed. Tests use fakes or temporary locations, never production data.
