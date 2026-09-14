# CDA Admin migration

```text
Source repository: NoCoder4you/CDA-Admin
Source commit: eeaf7db96c8e9080762e6b7c2b26984551653797
Source snapshot: migration-sources/cda-admin/
```

## Result

The original flat `bot.py` + `COGS/` + `JSON/` application is now the independent package
`bots/cda-admin/src/cda_admin/`, launched with `PYTHONPATH=bots/cda-admin/src python -m
cda_admin`. Every cog is present under `cda_admin/cogs`; static/sanitized bootstrap data is
under `cda_admin/defaults`; runtime files are beneath `MDBO_RUNTIME_ROOT/data/cda-admin`.
It has no portal or other-bot dependency. `bot.toml` uses Stage 1's schema and remains
disabled/manual until production cutover.

Python 3.10 is the source-evidenced minimum; the migrated bot requires 3.11+ because it
uses the Stage 1 core. Runtime
dependencies are discord.py `>=2.0,<3`, aiohttp `>=3.8,<4`, APScheduler `>=3.9,<4`; tests
use pytest `>=8,<9`. These compatible ranges were introduced because the source supplied
no versions, so exact version parity is uncertain. Installation is bot-local via
`requirements.txt`; test dependencies are in `requirements-test.txt`.

Configuration classifications: `CDA_ADMIN_TOKEN` is the only secret;
`MDBO_RUNTIME_ROOT` and `MDBO_LOG_LEVEL` are deployment configuration; the channel map,
role/group mapping, fixed Discord IDs, schedules, prefix, status text and rules are
application/business configuration; verification/admin/punishment/niceblock records are
persistent data; transient task/API/alert state is runtime state. No real secret was found
or migrated. All-intents operation requires enabling the privileged intents for the bot in
Discord. The operational snowflakes were preserved rather than creating an unmanageable
environment-variable surface.

## Data mapping and bootstrap

| Old path | New production path | Classification/default |
|---|---|---|
| `JSON/admins.json` | `runtime/data/cda-admin/admins.json` | mutable; admin schema retained |
| `JSON/niceblock_users.json` | `runtime/data/cda-admin/niceblock_users.json` | mutable; corrected empty default to the list the code requires |
| `JSON/punishment.json` | `runtime/data/cda-admin/punishment.json` | mutable production data; empty schema-only default |
| `JSON/rolesbadges.json` | `runtime/data/cda-admin/rolesbadges.json` | business configuration; source mapping bootstrapped |
| `JSON/server.json` | `runtime/data/cda-admin/server.json` | mutable production data; channels retained, user/state collections empty |
| `JSON/verification_codes.json` | `runtime/data/cda-admin/verification_codes.json` | ephemeral persistent state; empty schema default |
| `statuses.txt` | packaged `defaults/statuses.txt` | static application data |
| `server.json.save` | no source destination | production backup; migrate only during controlled cutover if needed |
| `bot_errors.log` | stdout/stderr (future supervisor capture) | no committed log file |

`RuntimePaths` validates bot IDs and traversal boundaries. First access atomically creates
the applicable sanitized/default JSON. Existing save functions retain their JSON layouts;
production cutover must copy actual current state over bootstrap files after backup and
validation. No production user list or punishment list was duplicated into migrated
source.

## Required behaviour changes

Previous behaviour: token was an empty source literal and startup failed at Discord.
Required change: require `CDA_ADMIN_TOKEN`.
Reason: safe secret handling.
New behaviour: startup validates the environment before connecting.
Compatibility risk: deployment must provide the variable.

Previous behaviour: data/log/status paths depended on source/CWD or `/home/pi/...`.
Required change: use Stage 1 runtime isolation, packaged statuses, and structured stdout.
Reason: portability, isolation, supervisor compatibility, and no committed logs.
New behaviour: mutable files resolve under `runtime/data/cda-admin`, traversal is rejected,
and timestamped records identify `cda-admin`.
Compatibility risk: production data must be copied during cutover.

Previous behaviour: every READY tried to load every extension again.
Required change: gate loading once per process while retaining per-extension failure
isolation, and use package-qualified extension names.
Reason: reconnect/package lifecycle correctness.
New behaviour: reconnect does not duplicate/reload cogs; owner load/reload commands remain.
Compatibility risk: an extension that failed once needs explicit load/reload or restart.

Previous behaviour: three cog tasks/schedulers survived extension unload.
Required change: cancel/shutdown them from `cog_unload`.
Reason: prevent duplicate work after owner reload and permit graceful shutdown.
New behaviour: AwaitingVerificationCleanup, ServerVerify and ServerPayAnnounce clean up.
Compatibility risk: none expected.

Previous behaviour: an empty object in `niceblock_users.json` caused `.append` failures.
Required change: bootstrap the list schema consumed by the code.
Reason: the committed value contradicted runtime logic.
New behaviour: fresh installs start with `[]`; copied production data is otherwise preserved.
Compatibility risk: an existing object-shaped file must be reviewed before cutover.

The self-exec `restart` command remains for compatibility, though supervisor-owned restart
is deliberately deferred. Manual command sync, messages/embeds, API behaviour, fixed IDs,
checks, roles, schedules, prefix, commands and error responses are otherwise retained.

## Tests and uncertainties

Offline tests characterize configuration, isolated/bootstrap paths, traversal rejection,
admin and niceblock schema round trips, cog discovery, packaged statuses, admin+Verified
checks, role-audit rules, and the original Habbo pacing/retry/encoding/reuse behaviours.
They use temporary paths and fake HTTP responses and do not connect to Discord or Habbo.
The sole original test suite was retained with only `COGS` changed to the package import.

Remaining uncertainties are exact original package versions, production timezone/service
unit/file ownership, whether helper-extension load failures were intentional, intended
authorization for apparently unchecked destructive/information commands, and whether live
state has diverged from this snapshot. Deferred debt: central atomic conversion of every
legacy writer, explicit timeouts/retries for non-RoleUpdater Habbo calls, truly persistent
view registration, removing duplicate `process_commands`, externalizing selected deployment
IDs, and replacing self-exec restart. Compare these patterns—JSON schemas, verification,
Habbo client behaviour, IDs, schedulers, permissions and restart semantics—with CDA Pay in
Stage 3 before extracting any shared business code.

## Production cutover (manual, non-destructive)

1. Identify and record the old CDA Admin service/process and current working directory.
2. Stop the old bot cleanly and confirm it no longer connects.
3. Create a timestamped backup of all JSON, statuses and service configuration.
4. Validate backup readability/checksums and parse every required JSON file.
5. Prepare the isolated `runtime/data/cda-admin` directory.
6. Copy required current persistent data according to the table (do not move/delete it).
7. Parse and schema-check the copied JSON; specifically review niceblock's list shape.
8. Set least-privilege ownership and permissions for the bot service account.
9. Configure `CDA_ADMIN_TOKEN`, `MDBO_RUNTIME_ROOT`, and log level outside Git.
10. Install only `bots/cda-admin/requirements.txt` in its environment.
11. Validate the manifest, then start only migrated CDA Admin.
12. Verify the independent process state.
13. Verify Discord connected state separately.
14. Verify Discord READY and that cogs/tasks loaded once.
15. Test critical help, verification, admin checks, role update and announcement paths in a
    controlled channel; explicitly run owner `sync` if slash registration requires it.
16. Inspect structured logs for extension/API/permission errors and ensure no secret appears.
17. Retain the stopped old deployment and timestamped backup unchanged.
18. If any validation fails, stop the migrated process, restore permissions/state from the
    verified backup if changed, and restart the old service only.
19. Retire the old deployment only after an agreed observation period and successful checks.

No live Raspberry Pi, destructive data migration, portal work, or Stage 3 work is included.
