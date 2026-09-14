# CDA Admin authoritative inventory

## Provenance and inspection

The only source used was the complete committed snapshot `migration-sources/cda-admin/`:

```text
Repository: NoCoder4you/CDA-Admin
Commit: eeaf7db96c8e9080762e6b7c2b26984551653797
```

Every file in the snapshot was enumerated and read: `bot.py`; all 26 Python files in
`COGS/`; `tests/test_role_updater.py`; all six `JSON/*.json` files; `server.json.save`;
`statuses.txt`; `.gitignore`; and the IntelliJ/PyCharm XML/project files. The snapshot is
recognisably the CDA moderation/verification/admin bot: it contains Discord command cogs,
Habbo verification and role reconciliation, staff audit tools, scheduled announcements,
DM relaying, and its live-shaped JSON stores. There is no requirements file, packaging
metadata, service unit, README, CI configuration, or token loader.

## Original structure and startup/lifecycle

`bot.py` is a directly executed script. At import it configured an ERROR-level file and
console logger, created `commands.Bot(command_prefix="noah ", intents=Intents.all(),
help_command=None)`, registered prefix commands and one tree error handler, then called
`bot.run()` with an empty literal token. Its hard-coded log/status/server paths point to
`/home/pi/discord-bots/bots/CDA Admin/`. `on_ready` dynamically listed every non-dunder
`.py` in sibling `COGS`, attempted each as `COGS.<stem>`, started the 15-second status
loop if needed, and printed tree commands. It did not call `tree.sync()` automatically;
owner-only prefix `sync` does so globally. Loading from `on_ready` meant reconnects tried
to load already-loaded extensions. Exceptions loading individual cogs were logged and
startup continued.

Prefix commands in `bot.py`: `help` (full paged reaction help only for user
298121351871594497; support embed otherwise), owner-only `load`, `unload`, `rc`, `reload`,
`restart`, `sync`, and `stop`. Prefix cog commands: `addadmin`, `admins`, `cogs`, `leave`,
`delete`, `lc`, `lr`, `purgeall`, `rolescan`, `verscan`, `deletechannel`/`delchan`, and
`niceblock enable|disable`. Slash commands/groups: `/namechange`; `/va reset`; `/verify`;
`/admin bos|dnh|np|remove`; `/admin banned_agencies add|remove`; `/info`; and `/nem`.
No cooldown decorators occur. The prefix is literally `noah ` (some niceblock guidance
incorrectly says `!`).

Shutdown was `bot.close()` for `stop`; `restart` closed then `os.execv`'d the interpreter.
There was no explicit SIGTERM handler or top-level `finally`. RoleUpdater and
DailyAnnouncement clean up their loop/scheduler on unload; AwaitingVerificationCleanup,
ServerVerify, and ServerPayAnnounce did not. APScheduler uses a background thread for the
daily message and an asyncio scheduler for pay announcements. Reconnect safety existed
inside the two audit cogs through `_ready_once`, but not in extension loading. No views
are registered with `bot.add_view`, so views with `timeout=None` are not actually restored
across process restarts.

## Cog-by-cog inventory

* `AdminManager`: cached JSON admin allow-list and admin-only add/list prefix commands.
* `AwaitingVerificationCleanup`: every 15 minutes, after READY, DM then kick members who
  held role 1248310200939581594 for over 24 hours; 2.5 seconds between successful kicks.
* `BotCheck`: Verified, Grinch, and combined Discord Admins+Verified slash checks.
* `CogsLoader`: owner-only interactive red/green cog toggle buttons (300-second view).
* `DailyAnnouncement`: APScheduler midnight UTC announcement to channel
  1293689337065508928.
* `LeaveCommand`, `MessageDelete`, `NoahInfo`, `NoahPurge`, `delcha`: leave-guild,
  owner message deletion, channel/role listing, bulk purge, and manage-channel deletion.
  `leave`, `lc`, `lr`, and `purgeall` rely on the owner ID set by `NoahInfo` rather than
  decorators; the first explicitly compares it while the latter commands have no check.
* `NameChange`: `/namechange`, an indefinite Approve/Reject button view, Discord Admins
  role checks, nickname update, and verified-user Habbo-name mutation.
* `NoahAuditLog`: audit embeds for target owner member changes, commands/errors,
  interactions, bans, and leaves to channel 1374748024286351501.
* `NoahPing`: logs mentions of owner to channel 1375980861219934238.
* `RoleUpdater`: ten-minute and member-join Habbo group/motto reconciliation, role add/
  remove, welcome role handling, and logging for guild 1248307521119060028.
* `ServerPayAnnounce`: eight daily pay reminders at minute 45 (scheduler local timezone)
  using the `server.json` payannounce channel and fixed role IDs.
* `ServerUnVerify`: `/va reset`, restricted to either of two role IDs; updates
  `server.json` and Verified/Awaiting roles.
* `ServerVerify`: `/verify`, Habbo profile/motto verification, five-character codes,
  role assignment, welcome DM, and a 2.5-minute expiry loop (codes expire after 600s).
* `ServerVerifyBan`: watches newly verified users; Habbo lookups; BoS/DNH/NP and banned
  agency enforcement/admin slash groups; writes punishment JSON.
* `TwoWayMessage`: DM-to-private-channel relay in guild 1202999519986458765, a basic
  in-memory spam window, delayed autoreply, attachment forwarding, and owner autoreply.
* `UserInfo`: `/info` combining stored verification, Discord roles and Habbo profile.
* `VerifiedRoleAudit`: READY/member-update compliance scans; Ignore/Kick view; kick
  permission check; channel/role names plus employee/special/exempt role rules.
* `VerifyKick`: detects Verified-role users absent from JSON; READY/member-update scans;
  Ignore/Kick view; channel 1404605698960003123.
* `WelcomeDM`: helper only. `nem`: owner-only embed creation/edit modal. `nice`: transient
  “thats nice” message listener and mutable enable list. `paths`: relative JSON adapter.

Listeners are `on_ready`, `on_member_join`, multiple `on_member_update`, `on_message`,
`on_command`, `on_command_error`, `on_interaction`, `on_app_command_error`,
`on_member_ban`, and `on_member_remove`. Buttons are NameChange Approve/Reject and both
audit views' Ignore/Kick plus dynamic cog toggles. `EmbedModal` has message ID, title,
description and footer inputs. There are no other modals or scheduled jobs.

## APIs, pacing, and errors

Habbo endpoints are `www.habbo.com/api/public/users?name=…`, `/users/{id}/groups`, dynamic
`www.habbo.{hotel}` profile lookup in ban enforcement, and avatar-image URLs. RoleUpdater
is the robust path: one asyncio lock, initial 1s interval (0.25–8s adaptive bounds), five
attempts, URL encoding, Retry-After handling for 429, exponential delay for malformed 429,
5xx/client errors (maximum delay 30/60s depending branch), and a 25-success window before
20% acceleration. It reuses profile data. Other Habbo callers create ad-hoc aiohttp
sessions, have no explicit timeout/retry/cache, and generally return an error response or
empty result on non-200/client failure. Discord rate handling is mostly fixed 2.5-second
sleeps; Forbidden/HTTPException handling varies. Broad catches often print and continue.

Runtime logging is mixed `print`, root logging, and a Raspberry-Pi file handler. App-command
CheckFailure is silently ignored globally. Some handlers suppress HTTP/permission errors;
some broad catches hide detail. The token is an empty literal; no apparent token, API key,
password, private key, webhook secret, database credential, or secret-bearing URL was
found. This assessment covers the snapshot, not inaccessible Git history.

## Configuration and IDs

* **Secret:** Discord token (empty in source; migrated name `CDA_ADMIN_TOKEN`).
* **Deployment configuration:** Raspberry Pi paths; runtime root/log level; the primary
  guild and operational channel/role snowflakes; server.json channel map.
* **Application/business configuration:** command prefix, owner 298121351871594497,
  role/group mapping, verification timings, schedules, audit rules, messages/statuses,
  Habbo endpoints, and fixed guild/channel/role IDs.
* **Runtime state:** in-memory spam/autoreply state, alert de-duplication, embed cache,
  adaptive API pacing, loaded extensions, and running jobs/tasks.
* **Persistent data:** admins, niceblock membership, punishments, verification codes,
  verified-user map/balances/user channels, channel configuration, and role/group mapping.

Snowflakes are not secrets. All literals were reviewed individually. They remain business
constants for compatibility rather than becoming dozens of environment variables. There
is no confidently identifiable configurable guild-ID scheme beyond these literals.

## Files, schemas, and writes

All original JSON resolved beneath `JSON/` through `COGS.paths`, except obsolete
`SERVER_FILE` and the root `server.json.save`. `admins.json` is `{"admins": [int,…]}`;
`niceblock_users.json` is expected by code to be `[int,…]` although the committed file is
an empty object (a source defect); `punishment.json` has `banned_users` maps `BoS`, `DNH`,
`NP` keyed by Habbo name with `Reason`, plus `banned_groups` objects; `rolesbadges.json`
has `roles` categories containing role/group records and optional flags;
`verification_codes.json` has `verification_data` keyed by user; `server.json` has channel
snowflakes, `{user_id, habbo}` verified users, balances, and user-channel maps.

Writes occur in AdminManager, nice, NameChange, ServerVerify (server and codes),
ServerUnVerify (server), and ServerVerifyBan (punishments). They were direct non-atomic
writes. `rolesbadges.json` and `statuses.txt` are static business configuration.
`server.json`, its `.save` copy, punishment entries, verification codes, admins, and
niceblock membership are live/production-shaped data; the snapshot contains real-looking
user/Habbo records and is not copied into the migrated defaults. `.idea` is IDE state.

## Versions, platform, tests, and risks

The IDE metadata specifies Python 3.10; source uses PEP 604 unions and async extension
APIs, so 3.10 is the evidenced minimum. No dependency versions are recorded. Imports prove
requirements for discord.py 2.x, aiohttp, and APScheduler 3.x. The only source test is a
useful offline `unittest.IsolatedAsyncioTestCase` suite for RoleUpdater's rate limits,
adaptive bounds, reuse and URL encoding; it is migrated intact except its package import.

Fragile areas/risks: live-shaped data in source; no dependency lock; slash sync is manual;
all intents require privileged portal toggles; member caches are assumed; scheduler local
timezone differs from the explicitly UTC daily job; multiple on_message listeners call
`process_commands` and may duplicate command processing; helper modules are discovered as
extensions and fail because they have no `setup`; CogsLoader's original module prefix was
wrong; indefinite views are not restart-persistent; several destructive commands lack
obvious checks; direct writes could truncate JSON; ad-hoc API calls lack timeouts; restart
self-exec conflicts with ideal supervisor ownership. Exact historical Python/discord.py/
aiohttp/APScheduler versions, production service configuration, timezone, and intended
permissions for unchecked commands are **uncertain** because the snapshot does not say.
