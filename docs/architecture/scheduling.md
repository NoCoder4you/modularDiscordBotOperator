# Stage 15 scheduling architecture

Stage 15 keeps two failure and ownership domains separate. Existing Discord/business jobs remain in each bot process; the platform scheduler orchestrates only the closed administrative catalog. No business job was moved or changed.

## Administrative boundary

The allow-list is `backup.create`, `bot.restart`, and `commands.sync`. Backup parameters contain only a catalogued `plan_id`; the other types have no parameters. Start, stop, maintenance toggles, restore, cog operations, notifications, and business actions are deferred: unattended or missed execution has unsafe desired-state or business semantics.

Every browser operation is authorized by `DenyByDefaultAuthorizer` for the exact bot. Creation, editing, toggling, and deletion require `scheduler.manage` **and** the underlying permission. Run Now requires `scheduler.run` and the underlying permission. Viewing requires `scheduler.view`. Authentication or bot assignment alone is insufficient.

Immediately before scheduled execution, the service reloads the owner from the identity store, requires that it still exists and is enabled, and rechecks `scheduler.manage`, bot assignment, underlying permission, current catalog/version, bot support, and parameters. Failure suspends the task and records `authorization_revoked` or `capability_unavailable`; ownership is never transferred. Browser-created tasks cannot be system-owned. Stage 15 defines no system-owned tasks.

| Type | Bots | Existing service | Underlying permission | Prerequisite | Concurrency | Misfire/retry | Parameters |
|---|---|---|---|---|---|---|---|
| `backup.create` | CDA Admin only | Stage 14 `BackupService` | `backups.create` | typed plan available; Discord READY not required | forbid overlap plus BackupService lock | one run within 15-minute grace; no retry | trusted `plan_id` |
| `bot.restart` | all registered bots | Stage 9 boundary → Stage 7 `SupervisorService` | `bots.restart` | Supervisor lifecycle policy | forbid overlap plus Supervisor serialization | skip missed run; no retry | none |
| `commands.sync` | all catalogued bots | Stage 12 `BotOperationService` | `commands.sync` | current process and Discord READY, checked by Stage 12 | forbid overlap plus Stage 12 lock | one run within 15-minute grace; no retry | none |
| start/stop | deferred | — | — | unsafe desired-state semantics | — | — | — |
| maintenance enable/disable | deferred | — | — | missed disable could strand maintenance state | — | — | — |
| restore/cog actions | deferred | — | — | disruptive/non-idempotent unattended semantics | — | — | — |

`PlatformTaskAdapter` calls those services; scheduler code performs no Discord, process, systemd, file, backup-retention, or health derivation work.

## Schedules and time

Definitions are structured one-time, daily, weekly, or fixed-interval schedules. Recurrence has a 15-minute minimum; one-time dates are bounded to ten years. IANA zones are validated with `zoneinfo`, while planned/started/completed values are stored as aware UTC ISO-8601 values. Recurring local calculations preserve the IANA name.

For nonexistent spring-forward wall times, that day's occurrence is skipped. For an ambiguous autumn rollback time, fold zero (the first occurrence) is selected; the durable occurrence key prevents a second execution. For Europe/London, `01:30` on 29 March 2026 is skipped, while `01:30` on 25 October 2026 runs once at the first `01:30`.

Catch-up is at most one occurrence. The default grace is 15 minutes; beyond it the occurrence is durably claimed and marked `misfired`, never replayed. Restart tasks always skip missed execution. There are no automatic retries or backlogs.

## Persistence and ownership

`SQLiteSchedulerStore` has a transactional, versioned schema containing declarative task JSON, revisions, scheduling metadata, a unique `(task_id, occurrence)` claim, bounded execution history (100 per task by default), and a scheduler lease. It never stores callables or pickle. Opaque 128-bit hexadecimal task and execution IDs are not paths.

Claims are committed before invoking the underlying service. A restart cannot reclaim an occurrence. Startup changes abandoned `running` rows to `unknown`; destructive work is not repeated when completion cannot be proven. Underlying operation IDs are stored when returned. Editing uses an expected revision and fails with `stale_revision`. Delete is soft deletion, retaining history.

Exactly one dedicated local `SchedulerRunner` should run in production. A renewable SQLite lease prevents another process from executing concurrently; web workers only render/control tasks and never start runners. Shutdown stops new polling and releases ownership. The runner is bounded and executes due definitions serially; service-specific Stage 7/12/14 serialization remains authoritative for cross-operation conflicts.

Limits default to 200 active tasks, 25 per owner/bot, 100 history entries per task, small existing portal form limits, and existing portal mutation rate limiting. Run Now does not alter recurring next-run time.

## Explicitly absent interfaces

Stage 15 exposes no arbitrary cron expression, command, shell, PTY, stdin, Python eval/exec/import/callable, argv, systemd unit/process, HTTP request, Discord message, filesystem path/action, SQL, or serialized executable object.
