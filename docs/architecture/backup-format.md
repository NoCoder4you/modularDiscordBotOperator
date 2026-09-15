# Stage 14 backup format and architecture

## Decisions and trust boundaries

Stage 14 follows ADRs 0001–0005. `DenyByDefaultAuthorizer` remains authoritative and every
operation checks `backups.view`, `backups.create`, or `backups.restore` against the exact canonical
bot. The grants are independent. Restore grants no lifecycle authority; `SupervisorService` remains
the only lifecycle authority. No new ADR was required.

The service accepts only canonical bot, plan, and opaque backup IDs. A closed plan maps to Stage 13
typed resources. Callers cannot supply paths, filenames, members, destinations, or resource sets.
Stage 13 has established safe ownership and restoration semantics only for CDA Admin's
`channel-routing`, so the initial `cda-admin-configuration` plan contains only that resource. It
would be unsafe to infer contracts for the other discovered JSON stores.

## Format version 1

Each completed record is a platform-controlled directory containing `manifest.json` and a
`payload/` directory. It is not ZIP or TAR and is never extracted. A payload member is derived only
from a catalog resource ID and is mapped back through its typed adapter, never to a manifest-chosen
live destination.

The strict manifest contains: `backup_format_version`, opaque `backup_id`, canonical `bot_id`,
trusted `plan_id`, timezone-aware `created_at`, creator ID, status, total safe bytes, operation ID,
internal safety-snapshot marker, and resource entries. Each entry contains resource ID, kind,
schema version, source revision, SHA-256, byte size, and restart requirement. Unknown/missing or
duplicate resources, extra payload files, mismatched owner/plan/ID, future formats, size violations,
symlinks, malformed JSON, and hash mismatches fail closed.

IDs are UUID4 hex values with an exact 32-lowercase-hex grammar. Storage is rooted at one injected,
resolved platform directory and partitioned by catalog bot ID. Resolved containment and symlink
checks apply to roots, records, and members. Unknown disk files never enter the catalog. The portal
does not display paths. Downloads and imports are deliberately absent.

## Consistency, publication, and bounds

The typed resource adapter obtains a committed Stage 13 snapshot and revision. Creation is
serialized per bot, writes restrictive staging files below the trusted root, fsyncs each file,
validates the complete staged manifest, and atomically renames it before updating the catalog.
Failures remove staging state and never publish it. JSON restore uses Stage 13 revision-checked,
atomic persistence. Different bot locks are independent. No bot is stopped for backup.

Limits are 16 resources, 2 MiB per resource, 10 MiB per backup, 100 MiB per bot by default, and the
last 10 completed records per plan. Retention deletes only catalogued, validated IDs and protects an
active restore source. Internal pre-restore snapshots share the same bounded catalog and retention.
Disk/write failures become safe typed errors without deleting valid source data or publishing a
partial backup.

No eligible Stage 13 resource is SQLite-backed. Consequently version 1 includes no SQLite adapter.
A future eligible SQLite plan must use `sqlite3.Connection.backup`, validate integrity, and add live
WAL/transaction tests; copying a live database is forbidden.

## Restore transaction and recovery

Preview revalidates integrity and compatibility, reads current revisions, and emits only resource
IDs, revision identifiers, `changed`/`unchanged`, and restart requirements. It stores an opaque,
actor/bot/backup-bound server-side preview with current revisions and process instance. Confirmation
reauthorizes, reloads the catalog record, rechecks the full manifest and hashes, rechecks revisions
and process identity, and rejects drift as `stale_restore_preview`.

Before mutation the service creates a bounded internal snapshot. All resources are validated first.
Each commit uses its typed Stage 13 adapter. A later failure rolls already-applied resources back in
reverse order. Outcomes distinguish `restore_failed_rolled_back` from
`manual_recovery_required`. Post-write revisions are verified. The current one-resource plan is
atomic at the Stage 13 adapter boundary; the journal/snapshot algorithm truthfully provides
best-effort rollback rather than claiming cross-file atomicity for future plans.

Backup and restore audits contain actor, bot, request/operation/backup/plan IDs, resource IDs,
revision identifiers, result, and rollback result only. They contain no values, paths, credentials,
session/CSRF material, environment data, or exceptions.
