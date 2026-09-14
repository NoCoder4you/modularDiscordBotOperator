# CDA Pay Stage 3 migration

**Source repository:** NoCoder4you/CDA-Pay
**Source commit:** `c1aa74c2440c039779e4da06586799272d36aa2f`
**Source snapshot:** `migration-sources/cda-pay/`

## Layout, entry point, and dependencies

The source contains only nine `COGS/*.py` modules, static statuses/license, ignore rules, and a generated error log; it has no entry point, dependency declaration, tests, or JSON snapshot. The migration is `bots/cda-pay/src/cda_pay/`, with all source cogs under `cogs/`, package configuration/time/path modules, defaults, and offline tests. Run with `PYTHONPATH=bots/cda-pay/src:. python -m cda_pay`.

The monorepo requires Python 3.11; the source log proves Python 3.10 and code requires at least 3.9. Runtime compatibility ranges are `discord.py>=2.0,<3`, `APScheduler>=3.9,<4`, and `aiofiles>=23.2,<25`; exact source versions were not committed, so reproducing an exact source environment is impossible and no upgrade is claimed. Tests use pytest 8.x. Unlike CDA Admin, Pay needs APScheduler and aiofiles.

## Configuration, secrets, IDs, and state

`CDA_PAY_TOKEN` is the sole secret and is already represented safely in `.env.example`; the snapshot contains no credential literal. `MDBO_RUNTIME_ROOT` and `MDBO_LOG_LEVEL` are deployment settings. `server.json` is application/business configuration containing channel IDs, role names, timezone/reset time, and target user. Guild/user snowflakes and hard-coded role names remain business configuration. Monthly pay and void JSON are persistent runtime state; backup JSON is application backup data.

| Old source path | New path |
|---|---|
| `JSON/server.json` | `$MDBO_RUNTIME_ROOT/data/cda-pay/JSON/server.json` |
| `JSON/<MON_YEAR>.json` | `$MDBO_RUNTIME_ROOT/data/cda-pay/JSON/<MON_YEAR>.json` |
| `JSON/CDAVoidData.json` | `$MDBO_RUNTIME_ROOT/data/cda-pay/JSON/CDAVoidData.json` |
| `BACKUPS/*.json` | `$MDBO_RUNTIME_ROOT/data/cda-pay/BACKUPS/*.json` |
| `bot_errors.log` | not migrated; structured stdout/stderr is supervisor-owned |

`RuntimePaths.bot_data("cda-pay", ...)` enforces the bot ID and traversal boundary. No mutable/live production data is committed. Existing schemas, date keys, filenames, and backup bytes remain unchanged.

## Pay, timezone, scheduler, and backup behavior

The exact pay-window, adjacency/buffer, duplicate, daily/weekly totals, Sunday `7-8 PM` summary, Monday week-key, three-void ban, 24-hour rounded ban, and JSON semantics are documented in `cda-pay-inventory.md` and covered at key boundaries. Pay wall time is now explicitly `Europe/London`, avoiding dependence on the launching shell's host timezone while preserving UK production wall behavior and `YYYY-MM-DD` keys. Naive void ISO strings remain unchanged for compatibility, but “now” is London wall time.

The Sunday APScheduler job remains cog-owned, non-persistent, coalesced, and limited to a five-minute misfire grace. The backup task remains cog-owned: it selects the startup month, waits until configured London wall time, repeats every 24 hours, copies only the pay month, names `<MONTH>_<timestamp>.json`, and removes files older than seven days by `st_ctime`. January/month rollover still requires restart because changing this source behavior could select a different production file. No platform scheduler/backup was introduced.

Extensions now load once during discord.py `setup_hook`, not on every READY. This directly fixes the source-log lifecycle blocker where reconnects retried already-loaded extensions. Cogs still cancel/shut down their own tasks on unload; `Bot.close()` provides graceful discord.py cleanup. Logs use Stage 1 timestamped, bot-labelled stdout and avoid generated files/secrets. Management-agent support remains false; external management can report process/connection/READY and later heartbeat without making Discord dependent on it.

## Required behavioral changes

### Explicit UK wall clock

**Previous behavior:** pay/ban/month code used naive host-local time, while scheduler configuration said Europe/London.
**Required change:** select UK wall time explicitly where a portable launch otherwise changes pay dates/windows.
**Reason:** a supervisor may run with UTC or another host timezone; the production rules and configuration identify Europe/London.
**New behavior:** aware inputs and current pay time resolve in Europe/London; externally stored keys/labels and naive ban ISO shape are preserved.
**Compatibility risk:** if the old Pi intentionally used a non-UK timezone, boundary behavior changes; verify during cutover.

### Package paths and secret

**Previous behavior:** mutable directories lived beside source and token startup source was absent.
**Required change:** use Stage 1 isolated paths and `CDA_PAY_TOKEN`.
**Reason:** portability, secret safety, and cross-bot isolation.
**New behavior:** state is under `runtime/data/cda-pay`; package runs from any CWD.
**Compatibility risk:** production JSON must be copied before launch or defaults will be created.

### One-time extension loading and console logging

**Previous behavior:** omitted startup repeatedly attempted cog loading after reconnect (confirmed in log); one cog configured global logging and others printed.
**Required change:** load exactly once in `setup_hook` and configure bot-labelled stdout.
**Reason:** prevent duplicate schedulers/jobs and integrate safely with process supervision.
**New behavior:** reconnect READY only reports readiness; Discord's close unloads cog resources.
**Compatibility risk:** extensions no longer get accidental reconnect reload attempts; intended owner reload commands were not present in the authoritative snapshot.

## Testing, uncertainty, and deferred cleanup

Offline tests cover GMT/BST conversion, DST transitions, pay buffers/fallbacks, Sunday/Monday, month/year filenames, role/trial-role distinctions, weekly keys, JSON schema/round-trip, void reset, configuration validation, traversal rejection, and CDA Admin path isolation. Source tests could not be migrated because none exist. Tests do not connect to Discord or use a token.

Still uncertain: omitted original client prefix/intents/sync/token/status startup. The migration uses `noah ` and all intents based on source command/listener needs and Stage 2 comparison; commands are manually owner-synced. Production guild intent toggles and IDs must be confirmed. Known pay defects and scheduler recovery limitations listed in the inventory remain deferred rather than silently redesigned.

## Production cutover and rollback

Do not modify the Raspberry Pi during Stage 3. For a future cutover:

1. Identify the old CDA Pay service/process and record active scheduler jobs, current pay window/week/month, voids, and bans.
2. Stop old CDA Pay cleanly; confirm it cannot still perform Sunday/reset/backup processing.
3. Create a timestamped backup of all persistent state and validate that every JSON file parses and backup sizes/hashes match.
4. Prepare `$MDBO_RUNTIME_ROOT/data/cda-pay/{JSON,BACKUPS}` without starting the bot.
5. Copy state, validate JSON schemas, date keys, current Monday week key, month filename, void counts, ban ISO values, and backup history.
6. Set least-privilege filesystem ownership/permissions; configure `CDA_PAY_TOKEN`, runtime root, and log level outside Git.
7. Install only CDA Pay dependencies in its environment.
8. Reconfirm the old process is stopped, then start **only** migrated CDA Pay.
9. Verify process health, Discord connection and READY, exactly one backup loop and one void-reset job, London pay-window calculation, current state, and critical commands.
10. Inspect bot-labelled logs and ensure no token/state path errors or duplicate scheduled processing.
11. Retain the stopped old deployment and timestamped backup. Retire them only after an observation period.

Rollback immediately on timing/state mismatch: stop migrated CDA Pay first, preserve its changed state for investigation, restore the validated pre-cutover snapshot if any writes occurred, then start exactly one old process and verify scheduler/pay state. Never overlap old and migrated instances.
