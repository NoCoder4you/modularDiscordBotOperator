# CDA Pay source inventory

## Authority and inspection scope

This inventory was completed before migration code was introduced. The sole source is the committed snapshot `migration-sources/cda-pay/`, representing **NoCoder4you/CDA-Pay** at **`c1aa74c2440c039779e4da06586799272d36aa2f`**. Every one of its nine Python cog files (including the package marker), `.gitignore`, `statuses.txt`, `LICENSE`, and the committed generated `bot_errors.log` was inspected. There are no source tests, dependency lock/requirements file, bot entry-point source, JSON directory, README, or configuration files in this snapshot. Consequently, client construction and some startup details are uncertain; log evidence is identified as such rather than treated as missing source.

## Original tree and data classification

```text
COGS/
  LeaveCommand.py       prefix command
  MessageDelete.py      prefix command
  NoahAuditLog.py       listeners, server.json reader/writer
  NoahPing.py           mention listener, server.json reader/writer
  PayBackup.py          daily background backup and prefix command
  PayLookup.py          /admin lookup command
  PayVoid.py            /payvoid and weekly APScheduler job
  RecordPay.py          pay commands, reports, monthly JSON state
  TwoWayMessage.py      DM relay listener
  __init__.py
LICENSE                  static legal text
statuses.txt             static application configuration
bot_errors.log           generated runtime output (must not migrate)
.gitignore               development configuration
```

`statuses.txt` is static configuration, although no included source reads it. `bot_errors.log` is generated output and contains production operational metadata (session identifiers, absolute paths, exception data); it is not runtime state and will not be copied. No default/example JSON, live mutable JSON, backups, or test fixtures are present. The absent `JSON/` and `BACKUPS/` directories are runtime-created in cog imports/constructors.

## Runtime and startup

* **Python:** traceback paths prove Python 3.10. No declared version exists; `zoneinfo` requires 3.9+, and modern type syntax is compatible with 3.9+. Exact supported range is otherwise uncertain.
* **Dependencies:** imports prove `discord.py`, `APScheduler`, and `aiofiles`; exact installed versions are absent. Traceback API locations and async extension setup indicate discord.py 2.x. No external HTTP/API integration is implemented beyond Discord.
* **Entry point/client:** absent. Logs establish a discord.py client connected and loaded extensions named `COGS.<module>`, but command prefix, intents, token source, `help_command`, owner configuration, initial sync, and shutdown signal handling cannot be confidently established.
* **Cog discovery/order:** not present. Logs show all nine extension modules were attempted. Reconnects repeatedly attempted to load already-loaded extensions, strongly implying loading from `on_ready`; exact discovery logic/order is uncertain.
* **Reconnect:** discord.py resumed/reconnected automatically. Extension reload attempts on READY caused `Extension ... is already loaded` errors. This is a confirmed fragile lifecycle area.
* **Shutdown:** `PayBackup.cog_unload()` cancels its loop and `PayVoid.cog_unload()` shuts down its scheduler. Process/client shutdown and SIGTERM handling are absent/uncertain.
* **Logging:** `RecordPay` invokes global `logging.basicConfig(INFO)` and logs command exceptions. Other cogs print diagnostics/errors. The committed log uses timestamp/level formatting apparently configured by omitted entry-point code and includes Discord library output. No redaction or rotation is evident.
* **Linux/Raspberry Pi:** traceback paths show `/home/pi/discord-bots/...`, Python 3.10 virtualenv, and POSIX deployment. Cog data paths themselves are relative to resolved source files, not CWD. Backup cleanup relies on `st_ctime` (metadata-change time on Linux), not creation time.

## Discord surface

### Commands

* Prefix: `leave` (only user `298121351871594497`); `delete <message_id>` (bot owner); `backup` (role named `Foundation` or owner); `daystat <YYYY-MM-DD>` and `weekstat <YYYY-MM-DD>` (configured admin channel; `daystat` silently deletes wrong-channel invocation, `weekstat` also DMs); command prefix is uncertain.
* Slash: `/paystat(total_claiming, people_paid, paytime_paid, bonus_paid)`; `/editpay(record_id, total_claiming?, people_paid?, amount_paid?, bonus_paid?, pay_time?)`; `/payvoid(username)`; `/admin lookup(message_id?, record_id?, pay_time?, pay_date?, min_amount?, max_amount?, min_bonus?, max_bonus?)`.
* No modal exists. `PayTimeConfirmationView` has two buttons (`custom_id` `time1`/`time2`), a 600-second timeout, and is ephemeral. It is not registered as a persistent view and cannot survive restart.

### Listeners/events

`NoahAuditLog` observes member updates, prefix commands/errors, slash interactions/errors, and the configured target user's bot-attributed ban/kick; it audits bot-made nickname/role changes and leaves a guild after the bot bans/kicks that target. `NoahPing` forwards target-user mentions and content. `TwoWayMessage` relays DMs through per-username channels, rate-limits to five messages per ten seconds, and schedules an in-memory 120-second auto-reply (comment incorrectly says five minutes). Its guild is hard-coded as `1202999519986458765`; target/owner/autoreply user is `298121351871594497`. It uses presence status, therefore the member/presence/message-content intents are operationally relevant. Member/audit/guild listeners require guild/member/moderation visibility. Exact original intents are uncertain.

### IDs and permissions

No role or channel snowflake is committed. `server.json` supplies channel IDs: `admin_stats`, `paystat_allowed`, `payvoid_allowed`, `audit_log`, `backup_notifications`, and `mention_log`; absent/zero IDs disable associated behavior. Role names are `Payer`, `Trial Payer`, `Stat Edit`, and separately hard-coded `Foundation`. `paystat` checks only hard-coded `Payer` despite configuration and does **not** accept Trial Payer. `payvoid` accepts configured Payer **or Trial Payer**. `editpay` requires hard-coded `Stat Edit`; lookup and manual backup require hard-coded `Foundation`. The leave command and relay use the hard-coded user noted above. Discord IDs are application/business configuration, not secrets.

## Configuration and secrets classification

* **Secret:** Discord token is required by the omitted entry point; no token literal/source is in the snapshot. The phrase `token` in `RecordPay` is merely an error comment/log context. No API key, password, webhook secret, authenticated URL, or private credential literal was found. The committed log says static token authentication was used but does not print the token.
* **Deployment configuration:** runtime root, log level, process working directory, and token environment variable were absent.
* **Application/business configuration:** all `server.json` channel IDs, role names, timezone/hour/minute, `target_user`; hard-coded guild/user IDs; pay windows; cleanup age; spam and view timeouts.
* **Runtime state/persistent data:** monthly pay JSON, `CDAVoidData.json`, and backup files.

Each cog independently shallow-merges slightly different defaults. Invalid/missing `server.json` silently returns defaults; missing files are written by whichever cog first imports/loads, so resulting schema depends on load order. This is fragile and configuration validation is absent.

## Pay processing characterization

### Pay windows, timezone, and dates

`get_pay_time()` uses naive `datetime.now()` in the host timezone. Windows are 00–01, 01–02, 06–07, 07–08, 12–13, 13–14, 18–19, and 19–20, labelled in 12-hour text. During minutes 00–24 it offers the prior array entry and current entry; during minutes 50–59 it offers current and next. Because the array skips hours, 06:00–06:24 offers **`1-2 AM` vs `6-7 AM`**, for example. Outside all windows it chooses the most recent listed window in the previous hour, otherwise hard-coded `4-5 PM`, and dates that fallback using the previous hour. This means most invalid times are nevertheless accepted as `4-5 PM`; there is no reject-only “valid window” check.

No weekday restriction exists. A `7-8 PM` record triggers daily summary; if its `pay_date` is Sunday it also triggers weekly summary. Week keys are the Monday (`YYYY-MM-DD`) calculated from each record date. Date keys and `pay_date` use `YYYY-MM-DD`; month filenames use uppercase locale-dependent `%b_%Y` such as `DEC_2025.json`. Original pay code has no explicit timezone or BST/GMT conversion, so behavior depends on the Pi being configured to UK wall time. The backup scheduler alone explicitly uses configured `Europe/London`; its filenames still use host-local naive time. DST transition behavior in pay/ban code is therefore uncertain outside a UK-configured host.

### Records and totals

Monthly schema is exactly `{ "records": {}, "daily_totals": {}, "weekly_totals": {} }`. `records[pay_date]` is a list containing record ID, pay date/time, claim/paid/denied counts, `paytime_paid`, `bonus_paid`, `total_paid`, and later `message_id`. Five-digit random IDs are retried against all loaded-month IDs. Duplicate prevention scans the loaded month for identical `pay_date` plus `pay_time`; there is no persisted transaction marker/lock and concurrent invocations can race. Inputs do not reject negatives or `people_paid > total_claiming` during create. Daily/weekly fields are additive.

`editpay` changes the record and adjusts amount/paid/bonus totals by deltas, but assigns `people_denied` to that record's denied value rather than correctly aggregating all records. Its `total_claiming or old` expression also treats zero as absent. Lookup displays `amount_paid`, while records store `paytime_paid`, so that displayed field is normally `N/A`. These are preserved known defects, not inferred desired behavior.

Weekly summary uses the current naive date at send time rather than the recorded `pay_date`, then reads the corresponding Monday total. There is no monthly total distinct from the monthly file's daily/weekly aggregates, no scheduled Monday records reset, and no weekly pay-data deletion/reset. “Monday reset” applies only indirectly through a new Monday key. Missed Sunday summaries are not recovered after downtime.

### Voids and bans

`CDAVoidData.json` schema is `{ "voids": { normalized_username: { "void_count": int, "ban_until": null|ISO datetime } } }`. Usernames are stripped/lowercased as keys; labels preserve stripped case. At three voids the counter becomes zero and a 24-hour ban is created, rounded **down** to the hour. Voiding an actively banned name replaces (does not extend from existing expiry) the ban with another now-plus-24-hours rounded down. An expired ban is lazily cleared only when that name is voided again, then the new void becomes count one. Datetimes are naive host-local ISO strings. Payer and Trial Payer roles are mentioned on bans.

An in-memory APScheduler starts in the cog constructor, timezone from configuration, with a Sunday cron at configured hour/minute, `coalesce=True`, a five-minute misfire grace, and fixed job ID. It clears all voids. Jobs are not persisted; downtime beyond grace is not recovered. Multiple cog instances could duplicate schedulers, although normal extension loading creates one and unload shuts it down. The source's “Monday reset” wording is not implemented: the default is Sunday 23:00 Europe/London (some cog defaults differ, with backup default midnight).

## Backups

`PayBackup` chooses its monthly source file once at cog construction from naive host-local time. It creates the monthly JSON and `BACKUPS/` directories/file when absent. After Discord READY, the loop waits until the next configured wall time using `ZoneInfo` (if now equals/passes it, next day), then runs every fixed 24 hours. This fixed interval can drift by one wall-clock hour across UK DST. It copies only that initially selected monthly pay JSON, byte-for-byte, to `<MONTH_STEM>_<YYYYMMDD_HHMMSS>.json`; it does not back up voids or server config. The month source is **not rolled over after month change**, so a long-running process continues backing up the startup month. January behaves the same: a process started in December continues backing up December until restart. Filename timestamps are naive host time.

After backup it deletes every file in the backup directory whose Linux `st_ctime` age is over seven whole days; there is no count-based retention. Errors are printed and swallowed. A configured channel receives the backup as an attachment. Manual backup has Foundation/owner checks. No restore implementation or validation exists; restore assumptions are uncertain.

## Runtime writes and failure handling

Writes are `JSON/server.json`, `JSON/<MON_YYYY>.json`, `JSON/CDAVoidData.json`, and `BACKUPS/*.json`; directories are made at import/constructor time. Writes use direct overwrite and are neither atomic nor locked, so interruption/concurrency can corrupt JSON. JSON decoding errors generally fail cog construction except server config, which silently defaults. Command errors are inconsistent: paystat logs and gives no final user error; editpay returns a generic ephemeral error; backup prints/swallow errors; Discord delete handles common HTTP errors. No database, Redis, platform backup, or external filesystem is used.

## Existing tests, uncertainties, fragile areas, and risks

There are **no source tests**. Most important risks are: missing authoritative entry point/dependency metadata; host-local time dependence; DST and fixed-24-hour backup drift; month captured only at cog startup; naive serialized bans; non-atomic state; duplicate race; inconsistent server defaults/configured role usage; scheduler non-persistence; READY-driven duplicate load evidence; untracked auto-reply tasks; username-based DM routing collisions; lookup field mismatch; aggregate corruption in edit; absent validation; logs committed with production metadata. Behavior that depends on omitted code—prefix, intents, owner/application IDs, token loading, sync timing, status rotation, graceful signals—is explicitly uncertain and must be supplied as migration lifecycle infrastructure rather than claimed as preserved source behavior.
