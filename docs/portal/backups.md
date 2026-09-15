# Per-bot backup management

The server-rendered Backups section is visible only when the identity has `backups.view` for that
exact bot. Create additionally requires `backups.create`; preview and confirmation require the
separate high-impact `backups.restore`. Authentication, `bots.view`, configuration permissions, and
lifecycle permissions do not imply any backup permission. Mutations use existing same-origin,
session-revision, request-size, CSRF, request-ID, safe-error, and rate-limit boundaries.

The list and detail pages expose safe metadata only: opaque ID, time, plan, status, format, size,
integrity, resource IDs, schema versions, and restart requirements. They do not expose backed-up
business values or storage paths. There is no download, delete, upload/import, archive browser,
filesystem browser, arbitrary destination, raw JSON/SQL, shell, scheduler, or cross-origin API.

## Resource matrix

| Bot | Resource | Included | Importance | Store | Consistency | Restore | Stop | Hot reload | Restart | Retention | Sensitivity | Reason |
|---|---|---:|---|---|---|---:|---:|---:|---:|---|---|---|
| cda-admin | channel routing fields | yes | important | typed JSON projection | Stage 13 lock/revision | yes | no | no | yes | last 10/plan | internal | owned schema and atomic adapter |
| cda-admin | verified users | no | required | mixed JSON document | read-only snapshot | no | — | — | — | — | restricted | Stage 13 exposes read-only data, not restore |
| cda-admin | roles/admins/punishment/codes/balances | no | required | mixed JSON | unknown | no | — | — | — | — | security-critical | schema/ownership deferred |
| cda-pay | routing/pay/void/time-partitioned state | no | required | JSON/tasks | existing direct writers | no | — | — | — | — | payroll-critical | Stage 13 deferred |
| unbot | tracker/snapshots/histories/presence | no | important | distributed JSON/tasks | mixed concurrent writers | no | — | — | — | — | restricted | Stage 13 deferred |
| rpa-admin | config/roles/verification/moderation/workflows | no | required | distributed stores/tasks | store-specific | no | — | — | — | — | security-critical | Stage 13 deferred |
| all | `.env`, tokens, OAuth/session/management secrets, private keys | no | secret | environment/credentials | n/a | never | — | — | — | — | SECRET | never portal-backed |
| all | venvs, source/cache/temp/log files, defaults, `.git`, OS/systemd/proxy | no | reproducible/excluded | host/source | n/a | no | — | — | — | — | excluded | not bot-owned mutable state |

The closed allow-list is the primary secret-exclusion control. Only declared typed fields are
serialized, so unrelated portions of a mixed document cannot enter a backup. Strict manifest member
validation provides defense in depth; heuristic secret scanning is not treated as a security
boundary.

## Existing bot backup behavior

No existing mechanism is replaced. CDA Pay's historically named backup/time-partitioned artifacts
and any bot-owned tasks remain unchanged and are not catalogued by Stage 14. CDA Admin Stage 14
coexists as a narrowly projected configuration backup. UNBOT and RPA Admin remain unchanged pending
typed persistence contracts. This avoids silently duplicating broad bot-specific retention.
