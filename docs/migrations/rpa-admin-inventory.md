# RPA Admin authoritative-source inventory

## Provenance and method

This inventory was completed **before migration implementation** from the complete committed
snapshot `migration-sources/rpa-admin/`. The authoritative revision is repository
`NoCoder4you/RPA-Admin`, commit `8843a6a978231ed24ecfda269785ea62520ced3d`. Every Python file,
all 25 source test files, all cogs, JSON files, helper modules, repository/configuration files,
and both source documentation files were inspected. Nothing here is inferred from CDA Admin,
CDA Pay, or UNBOT.

## Original layout and platform assumptions

The root contains `bot.py`, `common_paths.py`, `habbo_verification_core.py`, `statuses.txt`,
`COGS/` (22 loadable extensions plus `__init__.py`), `JSON/` (four committed files), `tests/`,
`docs/autoroles-cog.md`, `README.md`, IDE metadata, `.gitignore`, and a Codex environment file.
There is no packaging metadata, requirements file, CI configuration, service file, or updater
script (although one obsolete test expects `updater.sh`). `common_paths.PROJECT_ROOT` is the
directory containing that helper and exposes `JSON`/`COGS` paths independent of CWD. A few cogs
instead derive state from their own file location. No `/home/pi` literal or database is present.
Linux/Raspberry Pi deployment is suggested only by the requested migration context; the snapshot
does not confidently establish the service manager, OS user, working directory, or Python binary.

The syntax uses `X | None`, built-in generic types, `str.removeprefix`, `zoneinfo`, and async
extension setup, implying Python 3.10+; the platform baseline is Python 3.11. The source imports
`discord`/`discord.ext`/`discord.app_commands` and `aiohttp`. No dependency versions are recorded,
so the exact source discord.py version is **uncertain**; async `setup` and `Bot.tree` require the
discord.py 2.x family. Standard-library `urllib` supplies most Habbo calls.

## Startup, Discord client, loading, and lifecycle

Importing source `bot.py` immediately reads `ENV/.env`, accepts `BOT_TOKEN`, constructs a bot,
and configures a root file/console logger. It uses prefix `RPA `, removes the default help command,
and enables `discord.Intents.all()` (including privileged members, presences, and message content).
At module bottom it runs an async `main`: enter `async with bot`, load every visible `.py` in
`COGS/` using unsorted `os.listdir`, then `bot.start(TOKEN)`. Individual extension failures are
logged and startup continues. Extensions are `COGS.<filename>` and each has async `setup(bot)`.

`on_ready` starts the 15-second status loop only if it is not already running, preventing reconnect
duplicates; it prints identity/ready text and does not automatically synchronize application
commands. Owner-only prefix commands `load`, `unload`, `rc`, `reload`, `restart`, `sync`, and
`stop` provide lifecycle control. `reload` pauses one second between every extension. `restart`
closes the client and replaces the current process with `os.execv`. `async with bot` provides
discord.py shutdown; source-owned aiohttp sessions in the autorole updater are closed by its
`cog_unload`. SIGTERM handling is not explicit and management heartbeat reporting does not exist.
Status text is randomly selected from `statuses.txt`; the committed file is empty, producing the
fallback `Default status message.`. Logging goes to root-relative `bot_errors.log` and stdout,
with timestamp/level but no explicit bot field; prefix/slash successes and failures can also be
mirrored to fixed channel `1484064305732259940`. The token is not logged.

## Command, cog, event, UI, and task inventory

All extension files are runtime-loaded:

* `AutoInviteCog`: `on_member_update`; reads interlinked role configuration and creates a unique,
  single-use invite when a configured main-server role is newly gained.
* `HabboOnlineTimeCog`: `/onlinetime`; employee-only lookup of Habbo profile data and online-time
  calculation. Its provider request uses a 15-second timeout.
* `MentionForwardCog`: `on_message`; forwards messages mentioning fixed user/role targets to owner
  ID `298121351871594497`, with bot-owner bypass rules.
* `MiscBan`, `MiscKick`: `/ban`, `/kick`; caller and bot permission decorators enforce the matching
  moderation permission and hierarchy/self/owner checks.
* `MiscMute`: `/mute`; duration parsing, Discord timeout plus a managed `Muted` role, channel
  overwrites, `mute_timeouts.json`, a one-minute expiry loop, and channel-create listener.
* `MiscPurge`: `/purge all|bots|users|member`; manage-message permission, limits 1–1000, filtered
  bulk deletion and result/error embeds.
* `MiscProfanity`: message/create-edit listeners; normalized configured word detection, deletion,
  staff logging, and a one-hour non-persistent `Ignore`/`Proceed` button view.
* `MiscGiveaway`: `/giveaway start|end|reroll|list`; persistent records, an enter button/view,
  eligibility based on role/account age/join age, duplicate entry prevention, scheduled end tasks,
  random sampling, winner DMs/announcements, rerolls, and restart restoration. The view is recreated
  from state but uses a finite timeout; whether it meets Discord's strict persistent-view definition
  is **uncertain**.
* `MiscRaffle`: `/raffle create|add|remove|entries|draw|end|list`; detailed below.
* `PayAnnounceCog`: 30-second America/New_York pay-window checker over eight boundary strings;
  persistent schedule state prevents duplicate announcements.
* `PayVoidCog`: `/pay void`, `/pay reset`, and prefix `resetvoids`; persistent pay-discipline state,
  one-minute Monday-cycle reset loop, fixed guild/channel/role IDs, threshold three.
* `ReactionRoleCog`: prefix `reactionrole add|create|remove|list`, ready restoration and raw reaction
  add/remove listeners; manage-roles required and JSON mapping persists.
* `ServerAuditLog`: listeners for message delete/edit, join/leave, ban/unban, channel/role create,
  delete/update, member changes, guild update, and voice state. Server-configured channels are used.
* `ServerAutoRolesRPA`: 10-minute verified-user Habbo/role reconciliation, `/uva` (Manage Roles),
  and returning-member listener; described below.
* `ServerEmbedMaker`: `/embedmaker` (Manage Messages), opening a modal with title, description,
  colour, image and footer inputs; no persistent view.
* `ServerRules`: prefix `rules`, ready/reaction/member-update listeners, rules acknowledgement,
  verification staging role and onboarding instructions.
* `ServerSpecialUnit`: join listener mirroring configured main/special-unit roles.
* `ServerSterileChannel`: message listener and prefix `sterile add|remove|list`; manage-channels on
  the parent command, persistent channel list, deletes non-owner messages in configured channels.
* `ServerVerifyRPA`: `/verify`, admin-only guild prefix `forceverify`, verification reaction listener.
* `UserNameChange`: `/usernamechange`; request plus staff `Approve`/`Deny` button view (custom IDs,
  no timeout), profile validation, mapping/nickname update, request-channel and admin-role routing.
* `UserVerifyRestrict`: `/dnh` and `/bos` add/remove; Manage Guild required.
* `WebhookApplicationChannelCog`: message listener for configured webhook archive messages and an
  `ApplicationClaimView` button; creates applicant channels and posts/claims notifications.

There are no traditional message commands besides those listed. Slash commands are global and
only synchronized manually by `RPA sync`. Views/buttons/modals are the giveaway entry view,
profanity decision view, embed-maker modal, username-change request view, and application claim
view. Persistent registration/recovery varies by cog; exact button survivability for all views
after restart is **uncertain** and must be preserved rather than redesigned.

## Verification and username mapping

Users enter staging by reacting with ✅, ☑️, or ✔️ to the configured verification message. Their
reaction is removed, role named `Awaiting Verification` is granted, and an onboarding embed/ping is
sent to fixed channel `1479391662076723224`. They then invoke `/verify username`. The command
defers ephemerally, fetches `https://www.habbo.com/api/public/users?name=<quoted-name>`, and issues
an in-memory, cryptographically generated eight-character uppercase/digit motto code lasting five
minutes. Repeating the command for the same Discord user and case-insensitive username reuses a
live challenge; changing the username or expiry creates another. There is no polling: users put the
code in their motto and rerun `/verify`.

Success requires the returned dictionary to contain `motto` and for that motto to contain the code
as a case-sensitive substring. The canonical returned `name` is saved, groups are fetched from
`https://www.habbo.com/api/public/users/<quoted-uniqueId>/groups`, configured group roles are
reconciled, role named `Verified` is granted, the awaiting role is removed, nickname becomes the
Habbo username, restrictions are applied, an audit is attempted, the challenge is cleared, and an
ephemeral success embed is returned. Group mapping selects the first matching employee rank in
JSON order, all matching special/misc/donor roles, and the configured base employee role where an
entry has `rpaemployee=yes`; stale managed roles are removed.

`VerifiedUsers.json` schema is a list of `{ "discord_id": <string>, "habbo_username": <string> }`.
Lookup/update keys are exact string Discord IDs; save replaces the first matching row or appends.
External usernames are not required unique, so multiple Discord users can map to one Habbo name.
Malformed/missing/non-list files read as empty. Malformed rows are normalized to strings rather
than rejected. Writes are direct `write_text`, non-atomic, unlocked, and exposed to lost-update or
partial-write races. User departure does not delete mapping. On rejoin, the autorole cog restores
current mapped roles, `Verified`, and nickname unless restricted. Stale mappings remain indefinitely.

Already-verified users cannot replace their mapping through `/verify`: the stored username is used,
baseline role/nickname are restored before API access, and the command only resynchronizes groups.
`/usernamechange` is the intended rename path: it validates the new public profile and creates a
staff approval request; approval updates the same mapping and nickname. Admin `RPA forceverify
<member> <username>` bypasses motto proof but still requires a successful profile lookup and then
performs the same persistence, roles, nickname, restrictions, and audit work. No other administrative
override/removal command was found.

API/network/invalid-response errors produce user-visible orange failure embeds and do not save a
first-time mapping. A missing motto field is invalid. No retry/backoff exists in the interactive
flow. Failed motto checks retain the challenge and show the current motto. Timeout occurs only by
challenge expiry; there is no proactive timeout message. DNH success removes managed employee
roles after saving verification; BoS attempts a DM then bans after saving. Permission/HTTP failures
in role, nickname, DM, ban and audit operations are converted to status messages/soft failure.

## Habbo and other HTTP integrations

Core verification uses blocking stdlib `urllib.request.urlopen`, GET, percent-quoted parameters,
10-second timeout, no shared client/session, caching, explicit user-agent, retry, backoff, or 429
special case. HTTP, URL, and timeout failures become `HabboApiError`; invalid JSON, wrong top-level
shape, or missing profile fields also become that error. A missing user therefore follows whatever
HTTP/body the public provider returns and becomes a generic API error; this is **uncertain** beyond
the code's generic handling. Avatar images use Habbo's public `habbo-imaging/avatarimage` URL.

The autorole updater independently uses one `aiohttp.ClientSession`, closes it on unload, makes
profile and group GETs, and paces starts with an adaptive limiter: target 150 requests/10 minutes,
floor 60, halve after HTTP 429, add 15 after 100 HTTP-200 responses. A 429 stops a batch, honors
`Retry-After`, or defaults to 30 minutes. Its employee motto safeguard reuses profile data. The
10-minute loop waits for ready and avoids a duplicate loop. `HabboOnlineTimeCog` also uses blocking
stdlib HTTP with 15-second timeout. Exact provider response longevity/rate-limit guarantees are
external and **uncertain**. Tests must patch these entry points; live calls are inappropriate.

## Raffle behaviour (distinct from giveaway)

Only a guild member with the role named `Rank Seller` may use the raffle group. `/raffle create`
creates an active, guild-scoped record with an uppercase eight-hex UUID-derived ID, creator,
timestamp, supplied name/description, fixed raffle log channel `1485484040055427132`, optional
multiple-entry policy, empty entrants/winners, and last-input actor. There is no user self-entry:
authorized staff use `/raffle add`. Inputs may be Discord ID/mention/name, a verified Habbo
username, or free text. Verified mappings connect known users to Discord keys and enable DMs/
Habbo thumbnails. Single-entry raffles reject duplicates; multiple-entry raffles increment counts.
Per-raffle locks serialize add/remove and failed Discord responses roll persistence back.

State is `raffles.json` with top-level `{ "raffles": {<id>: <record>} }`; it reloads on cog load,
normalizes compatible records, and recovers active raffles after restart. Missing state is created.
Malformed JSON is renamed to `raffles.corrupted.json` and reset; invalid shape resets. Writes use a
temporary sibling and replacement in the source implementation's save path. `/entries` paginates
at 20 displayed entrants. `/remove` decrements or deletes entries. `/end` only marks inactive;
there is no purge/reset command.

`/draw winners` requires at least one entrant and no more winners than unique entrants. Selection
is unique and weighted by each entrant's entry count, using `random.choices` repeatedly and removing
each selected user from the candidate pool. Drawing records winner IDs and immediately closes the
raffle. There is no raffle reroll command (the separate giveaway feature has reroll). Each resolvable
winner receives a DM card and the same card is mirrored to the raffle log; missing members still
receive a logged card where possible. The final announcement uses the Discord mention when the
member is present, otherwise `_display_entrant_label` from persisted `username`. This stored label,
including verified Habbo username resolution, is the pinned revision's winner username-display
behaviour and must not regress. Announcements include raffle ID, unique winner count, weighted pool
size, closed status and DM result. No time-based automatic raffle end exists.

## Persistent data, configuration, and every runtime write

Committed data classification:

* `JSON/BadgesToRoles.json`: static/business configuration (Habbo group-to-role IDs).
* `JSON/InterlinkedRoles.json`: sanitized/example deployment/business configuration.
* `JSON/serverconfig.json`: deployment/business configuration, mutated by store setters.
* `JSON/profanity_words.json`: static application/business configuration; contains offensive terms.
* `JSON/VerifiedUsers.json`: real-looking production verification state and therefore must **not**
  be copied as a migrated default. Its users are not secrets but are private operational data.
* `statuses.txt`: static status configuration (empty in the snapshot).
* Test temporary files: test fixtures/generated output only.

Runtime-created/mutated files found across helpers/cogs are `VerifiedUsers.json`,
`HiddenProfileAlerts.json`, `VerifyRestrictions.json`, `serverconfig.json`, `InterlinkedRoles.json`,
`raffles.json` plus `.corrupted.json`, giveaway state, pay-announcement state, pay-void/payban state,
`reaction_roles.json`, `sterile_channels.json`, `mute_timeouts.json`, and `bot_errors.log`. Exact
source filenames for the giveaway/pay state are retained in migration code; all must move from the
source/application tree to isolated `runtime/data/rpa-admin`, while logs move to
`runtime/logs/rpa-admin`. Direct writers range from simple `write_text` to raffle replacement;
atomicity is inconsistent. Schemas must be preserved, not converted to SQL/Redis.

Configuration is entirely file/constants plus token. `BOT_TOKEN` in `ENV/.env` is the only source
secret and no committed token/API key/password/private key/authenticated URL was found. The migrated
secret is `RPA_ADMIN_TOKEN`. Discord snowflakes (guild/channel/role/message/user IDs) are deployment
or business configuration, not secrets; numerous fixed IDs remain behavioural constants while
server-configurable IDs stay in JSON. Exact production values should be reviewed at cutover.

## Error handling and operational fragility

The bot logs global event, prefix-command and application-command exceptions. Most cogs catch
expected Discord Forbidden/NotFound/HTTP errors. Cog-load failures do not abort startup. Blocking
urllib calls occur on the Discord event loop and may stall it up to timeout. JSON handling differs
by cog, with several direct, unlocked, non-atomic writes. Dynamic load order is filesystem-dependent.
Manual command sync can leave slash commands stale. Broad all-intents requires privileged intent
configuration. Many IDs and role names are coupled to one production deployment. Owner help access
and mention forwarding are fixed to one user. `forceverify`'s permission error text references
`!forceverify` although the actual prefix is `RPA `; this source-visible mismatch is preserved.

Reconnect safety is explicit for the bot status loop and discord.py task loops generally start at
cog construction/load; unload cancellation is present where coded. Giveaway restoration and UI
registration are complex and fragile. Username-change/application persistent-view registration
after a complete restart is not confidently evident and is marked **uncertain**. State concurrency
outside raffle locks is fragile. The fixed logging channel fetch and all-intents cache assumptions
can fail softly. No explicit health/heartbeat, signal hook, state migrations, or backup mechanism exists.

## Existing tests and documentation assessment

The snapshot has focused unittest/pytest-compatible tests for audit logs, auto-invite, ban, paths,
embed maker, giveaway, online time, autorole updater and rate limiting, verification core/cog,
kick, mention forwarding, mute, pay announce/void, profanity, purge, raffle, reaction roles, rules,
special units, sterile channels, username change, restrictions, and webhook applications. These use
temporary directories and Discord mocks, and Habbo tests patch network calls. They are valuable
characterization coverage and should be migrated with package/path adaptations. Two tests are stale:
`test_owner_leave_cog.py` references absent `cogs.owner_leave`, and `test_updater_script.py` expects
absent `updater.sh`; these describe code not in the authoritative snapshot and should be documented
rather than fabricating implementation. Source tests sometimes skip when discord.py is absent.

The README only identifies the project and links autorole documentation plus auto-invite setup.
`docs/autoroles-cog.md` is substantial and generally matches code, but names a nonexistent
`VerifyRestrictionsCog.py` rather than `UserVerifyRestrict.py` and mentions a class name that differs
from the implementation; code is authoritative. There is no source deployment, configuration,
dependency, cutover, rollback, or complete command documentation.

## Migration risks and uncertainties

Highest risks are preservation of 22 independently interacting extensions, fixed deployment IDs,
privileged intents, blocking external requests, JSON race/atomicity differences, active giveaway/
raffle recovery, persistent component behaviour, command sync, role hierarchy, and safe migration of
private verified-user state without committing it. Package-qualified extension names and isolated
runtime paths must replace root imports/CWD assumptions without changing commands or schemas.
Exact original Python/discord.py versions, Raspberry Pi service details, production state filenames
not exercised in committed fixtures, provider guarantees, and persistent button recovery are
explicitly uncertain. No inference from sibling bots is used to fill those gaps.
