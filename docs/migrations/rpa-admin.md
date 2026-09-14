# RPA Admin Stage 5 migration

**Source repository:** `NoCoder4you/RPA-Admin`  
**Source commit:** `8843a6a978231ed24ecfda269785ea62520ced3d`  
**Source snapshot:** `migration-sources/rpa-admin/`

## Layout and process boundary

The flat source (`bot.py`, `common_paths.py`, `habbo_verification_core.py`, `COGS/`, `JSON/`) becomes an independently installable application at `bots/rpa-admin`: manifest and requirements at its root, Python package in `src/rpa_admin`, extensions in `src/rpa_admin/cogs`, sanitized configuration templates in `defaults`, and adapted offline tests in `tests`. Entry point is `python -m rpa_admin`. It creates its own Discord Bot and neither imports nor shares CDA Admin, CDA Pay, UNBOT, portal, or supervisor runtime objects.

Python 3.11+ is supported. The source provided no requirements/version lock; migration records discord.py `>=2.0,<3` and aiohttp `>=3.8,<4`, plus pytest `>=8,<9` for tests. discord.py and aiohttp overlap with other bots; RPA's explicit aiohttp use is its paced role updater. No portal dependency is required.

## Configuration, secrets, IDs, and state

`RPA_ADMIN_TOKEN` replaces source `ENV/.env`/`BOT_TOKEN`. `MDBO_RUNTIME_ROOT` and `MDBO_LOG_LEVEL` use established platform conventions. No credential was committed in the snapshot. Discord snowflakes in constants/default JSON are deployment/business configuration, not secrets; they include production guild, moderation/log/application/pay/giveaway/verification channels, role/message/user IDs and should be validated before cutover. Group-to-role and interlinked-role rules remain JSON.

Old paths map as follows:

| Source path | Migrated path |
|---|---|
| `JSON/VerifiedUsers.json` | `${MDBO_RUNTIME_ROOT}/data/rpa-admin/VerifiedUsers.json` |
| `JSON/raffles.json` and corrupted backup | `${MDBO_RUNTIME_ROOT}/data/rpa-admin/raffles.json` / `raffles.corrupted.json` |
| all other mutable/config JSON | `${MDBO_RUNTIME_ROOT}/data/rpa-admin/<same filename>` |
| `bot_errors.log` | `${MDBO_RUNTIME_ROOT}/logs/rpa-admin/bot_errors.log` |
| `COGS/*.py` | packaged, immutable `src/rpa_admin/cogs/*.py` |
| `statuses.txt` | packaged `src/rpa_admin/statuses.txt` |

Sanitized `BadgesToRoles.json`, `InterlinkedRoles.json`, `profanity_words.json`, and `serverconfig.json` are first-use defaults. The source's real-looking verified-user rows are not copied. Persistence schemas, identifiers, timestamps, raffle weighting, and direct-write semantics remain compatible. The platform RuntimePaths trust boundary supplies bot isolation and traversal prevention.

## Preserved behaviour

All 22 extensions and their command/listener names are retained: verification and force verification, role updater `/uva`, username change, restrictions, raffles, giveaways, moderation, pay void/reset/announcements, reaction roles, rules/onboarding, auto invites, special units, sterile channels, profanity, audit events, online time, embed modal, mention forwarding, and application claim workflow. Prefix remains `RPA `, all intents remain enabled, slash sync remains owner-triggered, and fixed embeds/messages/permissions/IDs remain source-equivalent.

Verification, Habbo API and raffle mechanics are specified fully in `rpa-admin-inventory.md`. In brief, verification is a five-minute in-memory motto challenge persisted on success to a string-ID mapping; API profile/groups determine canonical name and mapped roles; existing mappings cannot be overwritten by `/verify`; username changes require approval; forceverify requires Administrator. The core public Habbo requests are 10-second stdlib GETs without retry, while autoroles uses a closeable aiohttp session and adaptive 150-to-60 request pacing. Raffle management requires `Rank Seller`, supports staff-added free-text/Discord/verified identities, weighted unique random winners, immediate close on draw, restart persistence, and the pinned winner display fallback to persisted usernames.

Background work comprises the 15-second status loop, 10-minute Habbo role updater, one-minute mute cleanup, 30-second pay announcements, one-minute weekly pay reset, and restored giveaway end tasks. Lifecycle cancellation remains in cog unload hooks; the migrated module defers token validation to `main`, writes supervisor-friendly stdout/file logs, logs startup/shutdown, loads cogs once across reconnects, and relies on discord.py's clean close for SIGTERM/process termination.

## Required migration changes

| Previous behaviour | Required change | Reason | New behaviour | Compatibility risk |
|---|---|---|---|---|
| Import required `ENV/.env` with `BOT_TOKEN`. | Explicit environment config. | Safe secret handling/package imports. | `RPA_ADMIN_TOKEN`; import is offline-safe. | Deployment must rename/configure variable. |
| JSON lived beside code through mixed helpers. | Platform RuntimePaths. | Isolation, CWD portability, traversal safety. | Same filenames/schemas under `data/rpa-admin`. | State must be copied before cutover. |
| Extensions were `COGS.*`. | Package-qualified extensions. | Correct installed imports. | `rpa_admin.cogs.*`, same modules/commands. | Operator reload arguments should use basename or new qualified name. |
| Cog loading occurred in `on_ready` without a durable loaded marker. | One-time guard. | Avoid reconnect reload failures/duplication. | Loads once per process. | None expected. |
| Log lived beside source. | Isolated platform log path. | Writable immutable deployments and hygiene. | Same log plus stdout under bot log root. | Log collector path changes. |
| Production mapping was committed upstream. | Sanitized defaults only. | Privacy/state safety. | Operator restores production state. | Missing cutover state appears empty. |

No verification, raffle, permission, command, schema, database, or shared-core redesign was made.

## Test coverage, uncertainties, and debt

All useful source tests were copied and import/path-adapted, covering the cogs and core behaviours. The absent owner-leave cog test and absent updater-script test were not migrated because implementing nonexistent source would violate source authority; this decision is explicit. New tests cover token validation, CWD-independent bot-isolated paths, and traversal rejection. External HTTP remains mocked and Discord is never connected.

Uncertainties retained from source: exact historic Python/discord.py versions, Raspberry Pi service identity, provider guarantees, and full post-restart persistence of every non-giveaway button. Deferred debt includes blocking urllib on the event loop, inconsistent/occasionally non-atomic JSON writers, hard-coded deployment snowflakes, manual command sync, and possible future shared safe-JSON/session/lifecycle primitives. These require a later four-bot architecture review rather than Stage 5 business changes.

## Production cutover and rollback

1. Identify and record the old process/service, executable, owner, CWD, environment and active tasks.
2. Record verified-user counts/checksums, restrictions, active raffle/giveaway IDs, pay/mute/reaction-role/config state.
3. Stop the old bot cleanly and confirm it is no longer connected, preventing duplicate loops/actions.
4. Make a timestamped backup of every JSON/state file and validate readability, sizes, checksums and restore access.
5. Create `${MDBO_RUNTIME_ROOT}/data/rpa-admin` and `logs/rpa-admin`; set least-privilege ownership/modes.
6. Copy required state using the old-to-new table; validate JSON shapes, verified mappings, and any active raffle/giveaway state without drawing/ending anything.
7. Configure `RPA_ADMIN_TOKEN`, runtime root, privileged intents and validated Discord IDs; install only RPA requirements.
8. Validate manifest/import/config offline, then start **only** migrated RPA Admin.
9. Confirm process health, Discord connect/READY, all expected cog load records and fresh status activity.
10. Safely inspect verified lookups/role configuration, test Habbo connectivity without altering a user's motto/state, and inspect active raffle state without entry/draw/end actions.
11. Inspect logs for permissions, missing roles/channels, API errors, duplicate task starts and state writes. Retain old deployment and backup until an agreed observation window passes.
12. If state, commands, roles, API results or task behaviour differ, stop migrated RPA Admin, preserve its logs/state for diagnosis, restore the validated backup to the old location if it changed, restart only the old service, verify READY/state/tasks, and keep the migrated service disabled. Retire old deployment only after successful acceptance.
