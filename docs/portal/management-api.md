# Stage 9 management API contract

The API prefix is `/api/management/v1`. Every call requires the bearer authentication described in
`authentication.md`; JSON responses carry `X-Request-ID`. There are no request bodies, uploads,
path inputs, unit inputs, argv inputs, or generic commands. Requests larger than 4096 bytes are
rejected when a content length is supplied.

| Method and path | Permission | Input | Safe output | Service and side effect |
|---|---|---|---|---|
| `GET /bots` | `bots.view` | none | accessible canonical IDs, display names, enabled flag, startup policy | `SupervisorService.list_bots`; none |
| `GET /bots/{bot_id}/health` | `bots.view` for bot | catalog ID | canonical state, safe evidence booleans, reason and state-change time | `HealthStore.get`; refreshes the authoritative snapshot only |
| `POST /bots/{bot_id}/start` | `bots.start` for bot | catalog ID; empty body | Stage 7 lifecycle result and operation | `SupervisorService.start` |
| `POST /bots/{bot_id}/stop` | `bots.stop` for bot | catalog ID; empty body | Stage 7 lifecycle result and operation | `SupervisorService.stop` |
| `POST /bots/{bot_id}/restart` | `bots.restart` for bot | catalog ID; empty body | Stage 7 lifecycle result and operation | `SupervisorService.restart` |
| `GET /operations/{operation_id}` | `operations.view` for operation bot | canonical UUID | existing Stage 7 operation status | `SupervisorService.get_operation`; none |

The adapter never starts a process, creates a lock, resolves a path, constructs argv, addresses a
systemd unit, or calculates canonical health. Stage 7 remains authoritative for operation identity,
serialization, idempotent errors, process identity, and crash behavior. Stage 8 remains the sole
reconciler; the API serializes `HealthSnapshot`, including its canonical heartbeat-fresh value.

Errors have the bounded shape
`{"error":{"code":"...","message":"...","request_id":"UUID"}}`. Stable codes are
`authentication_required`, `permission_denied`, `unknown_bot`, `bot_disabled`, `already_running`,
`already_stopped`, `operation_in_progress`, `operation_not_found`, `lifecycle_failed`,
`invalid_request`, `rate_limited`, `service_unavailable`, and `internal_error`. Raw exceptions are
never returned. Supervisor categories not explicitly safe-map to `lifecycle_failed`.

Bot IDs must match the canonical syntax and then resolve through the trusted manifest catalog.
Operation IDs must be canonical UUIDs and then resolve through Stage 7's operation store. Unknown or
malformed values fail closed and never become filesystem, process, shell, or systemd input.
