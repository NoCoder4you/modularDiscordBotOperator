# UNBOT authoritative-source inventory

## Provenance and inspection boundary

- **Repository:** `NoCoder4you/UNBOT`
- **Commit:** `3d43a9f5a4671f37db6d70bc35a126c1248e48ef`
- **Snapshot:** `migration-sources/unbot/` (read-only for Stage 4)
- Inspected files: root `bot.py`, `statuses.txt`, `.gitignore`, `LICENSE`; all three
  files in `COGS/`; and all three files in `tests/`. There is no dependency lock,
  packaging metadata, README, checked-in `JSON/` directory, database, view module,
  or service definition in the snapshot.

## Original structure and startup

`bot.py` is an immediately executing script. It constructs a `commands.Bot` with
prefix `noah `, no default help command, and `discord.Intents.all()`, then calls
`bot.run(TOKEN)` at import time. `TOKEN` is an empty source literal. The source does
not read a token from the environment. On every READY event, it discovers every
non-private Python file in the sibling `COGS` directory with unsorted `os.listdir`,
loads `COGS.<stem>` while logging and continuing after individual failures, starts
the status loop only if it is not running, and prints registered application
commands. Because extension loading itself is not guarded against already-loaded
extensions, reconnect READY events attempt loads again, log failures, and continue.
It does not automatically synchronize the command tree; owner-only
`noah sync_commands` does so manually.

The status loop begins after READY, runs every 0.25 minutes (15 seconds), reads
root `statuses.txt` on every iteration, chooses a random nonblank line, and sets a
watching activity. Missing/empty/unreadable input produces the literal fallback
`Default status message.`. The supplied static status configuration contains
`meow`, `oink`, `woof`, `baaa`, and `quack`.

The root commands are `help`, owner-only `load`, `unload`, `rc`, `reload`,
`restart`, `sync_commands`, and `stop`. Help is special-cased to user snowflake
`298121351871594497`: everyone else receives a transient Support embed; that user
receives reaction-paginated prefix-command help. `restart` closes the client then
uses `os.execv`; `stop` closes it. No custom signal handler exists, so source
shutdown otherwise relies on discord.py/asyncio. The cogs cancel their loops and
close their aiohttp sessions from `cog_unload`. There are no Discord UI Views,
buttons, modals, or persistent views.

## Runtime and dependencies

The source has no declared Python or dependency versions. Syntax (`X | None`,
built-in generic annotations) requires Python 3.10+, while Stage 1 supports Python
3.11+. It uses discord.py 2.x APIs: asynchronous extension setup/loading, hybrid
commands, app commands, task loops, interactions, and `Bot.tree`. Runtime imports
are `discord`/discord.py and `aiohttp`; all other imports are standard library.
Tests use `unittest` and synthetic modules and make no live network connection.
Exact source-installed versions and Raspberry Pi Python version are uncertain.

No explicit Raspberry Pi path occurs. The script assumes a writable checkout,
case-sensitive `COGS`/`JSON` naming, and a process able to replace itself with
`os.execv`; these are Linux-friendly but not explicitly Pi-specific.

## Cogs, commands, and listeners

### `HabboIdTracker`

Starts a five-minute profile loop in its constructor, protected by an asyncio scan
lock, after creating an aiohttp session with a 20-second total timeout. It tracks
immutable Habbo IDs matching `^[a-z]{2,5}-[a-f0-9]{16,64}$` against US Habbo
`GET https://www.habbo.com/api/public/users/{id}`. HTTP 200 dicts are accepted;
403/404 and malformed values become unavailable; other HTTP statuses and aiohttp/
timeout failures are logged, without retries or caching. Scalar public profile
properties are snapshotted. Although all property differences are calculated,
alerts are intentionally emitted only when `profileVisible` changes to false;
ordinary offline status and unrelated edits do not alert. The configured user is
mentioned in the configured channel with roles/everyone disabled. First observation
only establishes a snapshot.

Hybrid commands are owner-only `habboidadd`, `habboidremove`, `habboidchannel`, and
`habboidcheck`; `habboidlist` is not owner-restricted. Defaults are channel
`1528811302087032954` and mention user `298121351871594497`. The channel command
persists only the channel; no command changes the mention recipient.

### `HabboProfileWatcher` (`HabboWatch`)

Starts a five-minute loop in its constructor and waits for READY before its first
iteration. It has a shared one-request-per-second monotonic gate. Group rosters are
fetched page-by-page from `https://www.habbo.com/api/public/groups/{group}/members`;
profiles come from `https://www.habbo.com/api/public/users?name=<name>`. The fixed
groups are MOD `g-hhus-eb463e25366b3796072507bc69cbfee4` and OOA
`g-hhus-1685c3902d4ce5c8a4fcefa160fedaa2`. If a name belongs to both, OOA policy
overwrites MOD. HTTP 429 honors numeric `Retry-After` by delaying the shared gate;
other failures, connection errors, and malformed/non-dict responses are treated as
missing and logged. Forced actions try three times with 1- then 3-second delays;
routine scans make one request. After three consecutive routine failures per
profile, one owner summary DM is eligible, throttled to hourly by a roster-wide key.
Successful responses clear that profile's failure streak. Missing profiles retain
last known state and cannot create a false transition.

Slash commands are `check [username]`, `habbolastaccess`,
`offlinetimes <usernames> [include_history=true]`, and
`habbojson <username> <status> [timestamp] [policy]`. No app-command permission or
role decorators restrict these in source. Prefix owner-only `setmod [channels...]`
and `setooa [channels...]` replace persisted policy destinations, defaulting to the
invocation channel. Channel IDs may be old scalar values, lists, comma/space text,
mentions, or channel objects. Optional deployment defaults are
`HABBO_MOD_ALERT_CHANNEL_ID` and `HABBO_OOA_ALERT_CHANNEL_ID`; persisted nonempty
configuration takes precedence.

### `HabboUsernameFinder`

Creates an aiohttp session with a 15-second timeout. Hybrid command
`usernamefinder <username>` accepts 2–15 characters from letters, digits, dot,
underscore, and hyphen; it has no role/owner restriction. It checks exact and up to
ten generated/synonym close matches. Habbo 200 means taken, 404 deliberately means
unverified rather than available, and all other/malformed/failure results mean
unknown. It uses the watcher's API gate when available, otherwise its own one-second
gate; 429 delays the gate. Camel-case synonym lookup calls
`https://api.datamuse.com/words` with `rel_syn` and `max=5`, accepting only
single-word valid replacements. There is no cache or explicit retry.

There are no cog event listeners. The only events are root `on_ready`, `on_error`,
`on_command_error`, and tree error handling. Command errors are logged; application
check failures are silently ignored. Most watcher persistence errors are swallowed,
which preserves operation but can conceal data loss.

## Inactivity, offline policy, alerts, and time

All calculations use timezone-aware UTC `datetime.now(timezone.utc)` and ISO-8601
strings. Parsed naive timestamps are interpreted as UTC. There is no UK civil-time,
BST, server-local-time, calendar-day, or `Europe/London` calculation. Thresholds are
elapsed durations:

| Policy | Early | Near deadline | Deadline | Mention |
| --- | --- | --- | --- | --- |
| MOD | 2 days (`offline_mod_2d`) | 2 days 23 hours (`offline_mod_2d_23h`) | 3 days (`offline_mod_3d`) | deadline only |
| OOA | 16 hours (`offline_ooa_16h`) | 23 hours (`offline_ooa_23h`) | 24 hours (`offline_ooa_24h`) | deadline only |

Milestone resolution chooses the greatest reached threshold. Exactly the final MOD
3-day and OOA 24-hour keys are in `MENTION_ALERT_KEYS`; early alerts post without a
mention. Profile-hidden alerts are distinct and do not mention. If at least one
configured channel succeeds, no DM fallback is sent; otherwise the fixed user
`298121351871594497` receives a DM. Channel mentions explicitly permit users and
disable roles/everyone. There is no role mention and no exemption list beyond policy
membership determined by the two Habbo group rosters.

A user enters tracking by appearing in a fetched group roster. Online state is the
Habbo profile `online` value (falling back to `isOnline`) being exactly `True`.
Online observations continuously refresh last-online. An observed online→offline
transition seeds the policy clock from persisted last-online, falling back to now;
startup while already offline restores from active offline record, logoff time, or
last-online in that order. Habbo `lastAccessTime` can move persisted activity only
forward and can correct an offline start; a correction defers threshold notification
for one scan so the corrected time drives the next evaluation. An offline→online
transition archives the window, clears active logoff and sent-alert state, and sends
one back-online notification. A user disappearing from both rosters is simply no
longer scanned; source does not delete their persisted files/state. Role changes are
not relevant because policy comes from Habbo group membership, not Discord roles.

Duplicate milestone prevention exists in both in-memory `sent_alerts` and persisted
per-window `sent_alerts`. Restart restores both the active start and sent keys.
Starting a genuinely new offline window resets keys. Bot downtime has no scheduler
catch-up queue: the next successful scan evaluates elapsed UTC duration and emits
only the greatest currently reached unsent milestone; intermediate missed milestones
are not separately replayed. A five-minute polling delay applies. It is uncertain
whether the API's `lastAccessTime` precisely represents every kind of policy activity;
the source treats it as authoritative when newer.

The per-user audit allocates elapsed seconds between the previously observed state
and current state, using a known transition timestamp to divide restart gaps where
available. It records online/offline totals, current status/status-since,
last observation, policy, normalized/display names, and Habbo API account times.

## Persistence, configuration, and runtime writes

The source has no checked-in JSON/state. All following files are mutable runtime
state beneath checkout `JSON/` and are created on demand:

- `habbo_last_online.json`: lowercase username → ISO timestamp.
- `habbo_logoff_times.json`: lowercase username → active offline ISO timestamp.
- `habbo_offline_records.json`: display name, policy, last online, current offline,
  current-window `sent_alerts`, and completed `history` records.
- `habbo_alert_channels.json`: `mod`/`ooa` → Discord channel-ID lists.
- `USERS/<percent-encoded-lowercase-name>.json`: observation status/times, cumulative
  seconds, policy, and API timestamps.
- `habbo_tracked_ids.json`: ID → name/added-at metadata.
- `habbo_id_snapshots.json`: ID → scalar API snapshot.
- `habbo_id_changes.json`: append-only detected hidden-profile change records.
- `habbo_id_tracker_config.json`: alert channel and mention-user IDs.

Watcher top-level saves use direct `write_text`; ID tracker and per-user audit files
use same-directory temporary replacement. Formats and key casing must remain intact.
Root logging writes `bot_errors.log` beside source as well as stderr, another runtime
write. `statuses.txt` is static application configuration. `.gitignore` excludes
`JSON`, logs, environments, caches, and (unusually) `bot.py`.

Configuration classification: token is a **secret**; the two optional alert-channel
environment values and Discord IDs are **deployment configuration**; group IDs,
policy thresholds, intervals, API providers, messages, and statuses are
**application/business configuration**; `_state`, rate gates, failure streaks, and
hourly error dedupe are ephemeral **runtime state**; the JSON files are **persistent
data/runtime state**. A credential scan found only the deliberately empty token and
no API keys, passwords, webhooks, database credentials, authenticated URLs, or
private keys. Snowflakes and Habbo group IDs are not secrets.

## Scheduling, reconnect, shutdown, and errors

There are three independent task loops: 15-second status, five-minute ID tracker,
and five-minute profile watcher. Cog loops start during extension construction and
wait for bot READY; source decorators provide one running instance per cog object.
The status loop is explicitly protected against duplicate starts. Reconnect attempts
to reload all extensions, but failures leave existing instances/loops running.
There is no scheduled wall-clock start, timezone schedule, persistence of missed
runs, catch-up queue, exponential retry, or platform-wide scheduler. API gating and
the described limited retries are the only pacing/retry mechanisms.

Cog unload closes sessions. Normal bot close unload/session ordering is not made
explicit in source and graceful SIGTERM behaviour is therefore uncertain. Root logs
ERROR to checkout file and stream with timestamps but no bot identifier. Cogs use
module loggers. Exceptions in several state loads/saves and owner-DM fallbacks are
silently ignored; other API/notification failures retain username/channel context.

## Tests and risk assessment

`test_habbo_id_tracker.py` characterizes ID validation, snapshots, hidden-only
changes, first-scan behavior, persistence, and mentions. `test_habbo_profile_watcher.py`
extensively characterizes thresholds, exact mention suppression/deadlines, OOA
precedence, UTC parsing/arithmetic, state restoration/deduplication, online recovery,
audit files and schemas, safe filenames, API pagination/rate limiting/failure
aggregation, retry/fallback behavior, channel parsing/routing, manual operations,
last-access reconciliation, and forced checks. `test_habbo_username_finder.py`
characterizes validation, bounded suggestions, API status interpretation, Datamuse,
and shared gating. Tests dynamically replace Discord/aiohttp and therefore have no
token, network, scheduler, or production filesystem requirement.

Fragile areas and migration risks are: import-time root execution; CWD/package
extension strings; checkout-relative mutable data/logs; unsorted and reconnect-
repeated extension loads; direct non-atomic watcher writes with swallowed failures;
three independently owned HTTP sessions/gates (finder shares only when watcher is
available); live API schema/rate-limit assumptions; unrestricted slash commands that
mutate/query state; fixed owner/group/notification IDs; elapsed-time threshold
behavior around five-minute scans; and reliance on writable POSIX rename semantics.
Exact production dependency versions, service manager, filesystem ownership,
Discord application owner/team configuration, privileged intents enablement, and
whether all slash commands are intentionally unrestricted are uncertain from source.
