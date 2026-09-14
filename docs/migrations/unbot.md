# UNBOT migration (Stage 4)

**Source repository:** `NoCoder4you/UNBOT`
**Source commit:** `3d43a9f5a4671f37db6d70bc35a126c1248e48ef`
**Source snapshot:** `migration-sources/unbot/`

## Layout, entry point, and dependency boundary

The original root script plus `COGS/`, `statuses.txt`, and dynamically created
`JSON/` becomes an independently installable source tree at
`bots/unbot/src/unbot/`, with cogs under `cogs/`, static statuses under `defaults/`,
tests under `bots/unbot/tests/`, and a Stage 1 manifest. Run with
`PYTHONPATH=bots/unbot/src:. python -m unbot`. The process constructs only UNBOT's
client; it has no portal or CDA import/dependency.

The supported monorepo baseline is Python 3.11+. The snapshot declared no Python or
package versions, although its syntax requires 3.10+ and APIs require discord.py
2.x. Migration requirements conservatively specify `discord.py>=2.0,<3` and
`aiohttp>=3.8,<4`; pytest 8.x is test-only. discord.py/aiohttp overlap with both CDA
bots; UNBOT does not need CDA Admin's APScheduler. Bounds were added because the
source had no install metadata, not to upgrade production versions. Exact source
production versions remain unknown and should be recorded at cutover.

## Configuration and data mapping

`UNBOT_TOKEN` replaces the empty source token literal. `MDBO_RUNTIME_ROOT` and
`MDBO_LOG_LEVEL` use Stage 1 configuration. Existing optional
`HABBO_MOD_ALERT_CHANNEL_ID`/`HABBO_OOA_ALERT_CHANNEL_ID` remain supported. Tokens
are secrets; alert channels are deployment configuration; group/owner/default
channel IDs, statuses, intervals, API URLs, thresholds, messages and policy rules
are application configuration. Snowflakes are not secrets. The snapshot contains no
credential literal, real JSON, or production fixture.

| Old path | New path |
| --- | --- |
| `statuses.txt` | `bots/unbot/src/unbot/defaults/statuses.txt` |
| `bot_errors.log` | supervisor-captured structured stdout (normally `runtime/logs/unbot/` in future supervision) |
| `JSON/habbo_last_online.json` | `$MDBO_RUNTIME_ROOT/data/unbot/habbo_last_online.json` |
| `JSON/habbo_logoff_times.json` | `$MDBO_RUNTIME_ROOT/data/unbot/habbo_logoff_times.json` |
| `JSON/habbo_offline_records.json` | `$MDBO_RUNTIME_ROOT/data/unbot/habbo_offline_records.json` |
| `JSON/habbo_alert_channels.json` | `$MDBO_RUNTIME_ROOT/data/unbot/habbo_alert_channels.json` |
| `JSON/USERS/*.json` | `$MDBO_RUNTIME_ROOT/data/unbot/USERS/*.json` |
| `JSON/habbo_tracked_ids.json` | `$MDBO_RUNTIME_ROOT/data/unbot/habbo_tracked_ids.json` |
| `JSON/habbo_id_snapshots.json` | `$MDBO_RUNTIME_ROOT/data/unbot/habbo_id_snapshots.json` |
| `JSON/habbo_id_changes.json` | `$MDBO_RUNTIME_ROOT/data/unbot/habbo_id_changes.json` |
| `JSON/habbo_id_tracker_config.json` | `$MDBO_RUNTIME_ROOT/data/unbot/habbo_id_tracker_config.json` |

Schemas, timestamp strings, user identifiers, history, alert keys, and write behavior
are retained. `RuntimePaths.bot_data("unbot")` establishes the resolved capability,
rejects traversal, and cannot normally select a CDA root. No production state was
copied into Git.

## Behavior preserved

All root, hybrid, prefix, and slash command names/parameters, owner checks, embeds,
messages, fixed IDs, API interpretation, paging/rate gate/retries, 15-second status
rotation, five-minute loops, UTC arithmetic, MOD 2d/2d23h/3d and OOA 16h/23h/24h
milestones, persisted duplicate prevention, recovery notices, and profile-hidden
alerts remain intact. In particular, early offline milestones do **not** mention;
only `offline_mod_3d` and `offline_ooa_24h` mention the configured user. There are no
Discord roles, permission decorators on slash commands, exemptions, views, buttons,
or modals to migrate. API failure retains prior state; three consecutive routine
profile failures produce an hourly-deduped summary eligibility. UTC remains UTC;
Europe/London was not introduced because that would change elapsed policy semantics.

The source's three unittest suites were migrated and imports adjusted to the package
layout. They remain fully offline and characterize ID tracking, watcher policy/state/
time/API/scheduler helpers, and username lookup. Additional pytest coverage validates
required secret loading and cross-bot runtime isolation. No source test was omitted.

## Migration-required behavior changes

### Secret handling

**Previous behavior:** an empty `TOKEN` source literal was passed to `bot.run`.
**Required change:** load a nonblank `UNBOT_TOKEN`.
**Reason:** secure deployable configuration.
**New behavior:** startup fails before connecting with a configuration error when the
secret is absent.
**Compatibility risk:** deployment must provide the renamed secret.

### Package and lifecycle

**Previous behavior:** cogs were discovered as `COGS.*` and loaded during every
READY, causing noisy already-loaded failures after reconnect.
**Required change:** package-correct loading and duplicate-task prevention.
**Reason:** CWD independence and lifecycle correctness.
**New behavior:** `unbot.cogs.*` extensions load once in `setup_hook`; READY starts
the guarded status loop and reports readiness.
**Compatibility risk:** a cog added after process setup requires the preserved owner
load/reload commands or a restart, rather than a reconnect side effect.

### Runtime paths and logging

**Previous behavior:** JSON and an error log were written into the checkout.
**Required change:** isolate mutable state and make logs supervisor-friendly.
**Reason:** portability, safe ownership, and independent process management.
**New behavior:** JSON uses Stage 1's UNBOT data capability; timestamped bot-tagged
logs go to stdout without duplicate file handlers.
**Compatibility risk:** existing JSON must be copied before first production start;
operators must collect stdout.

## Production cutover and rollback

1. Identify the old UNBOT service/process and record its executable, owner, versions,
   token source, channel variables, and current tracking/alert state.
2. Stop old UNBOT cleanly so it cannot emit alerts while files are copied.
3. Create a timestamped backup of all `JSON/` state; checksum it and test-parse every
   JSON document without modifying the backup.
4. Create `$MDBO_RUNTIME_ROOT/data/unbot` with least-privilege ownership/modes. Copy
   JSON contents according to the table (the contents of old `JSON/`, not an extra
   nested `JSON` directory). Validate schemas, usernames, alert keys, and every
   date/time field; retain timestamps verbatim.
5. Install the independently bounded requirements in UNBOT's environment. Configure
   `UNBOT_TOKEN`, runtime/log settings, and optional channel defaults without placing
   secrets in files tracked by Git. Confirm privileged Discord intents.
6. Ensure CDA processes remain untouched. Start only migrated UNBOT. Verify process
   health, Discord connection and READY, and logs showing each background cog/loop
   exactly once.
7. Compare loaded tracking counts and active offline starts/sent-alert keys with the
   recorded state. Use read-only calculations or sanitized staging tests to validate
   thresholds; do not force production alerts. Inspect API/channel errors and allow
   at least one normal scan before acceptance.
8. Retain old deployment and backup until multiple expected cycles and a safe policy
   boundary pass. Avoid ever running old and new processes concurrently.

Rollback: stop migrated UNBOT first; archive its newer runtime state separately;
compare whether it emitted or changed alerts; restore the validated pre-cutover data
to the old layout with original ownership; restore old secrets/service configuration;
start only the old process; verify READY and one loop; inspect for duplicates before
resuming alerts. Investigate differences offline. Retire old deployment only after
successful validation.

## Uncertainties, risks, and deferred work

Unknowns are the exact production Python/dependency versions and service manager,
whether unrestricted state-changing slash commands are intentional, deployment
filesystem permissions, and the real API meaning/precision of `lastAccessTime`.
Risks include external schema/rate behavior, swallowed watcher save errors, direct
non-atomic writes for several legacy schemas, fixed organization IDs, and up-to-five-
minute deadline delivery. Broader atomic-storage conversion, a shared HTTP client/
scheduler/cog loader, policy authorization redesign, database modernization,
management heartbeat emission, and UK civil-time reinterpretation are deliberately
deferred. They are not safe Stage 4 behavior-preserving changes.
