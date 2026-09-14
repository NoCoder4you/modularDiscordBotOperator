# CDA Admin / CDA Pay comparison

## Confirmed common infrastructure

Both are separate discord.py 2.x `commands.Bot` processes, use async extension `setup`, environment-only token configuration, Stage 1 `PlatformConfig`/`RuntimePaths`, structured stdout logging, and the same manifest/lifecycle boundary. Both use JSON state and resolved package cog discovery. Stage 1 path validation, manifest parsing, state contracts, logging, and JSON utilities remain the appropriate shared layer.

No new shared extraction was made: CDA Admin's migrated cogs contain compatibility path modules/default materialization while CDA Pay's source has different state schemas, monthly partitioning, backup job, and void scheduler. Coupling these during a behavior-characterization migration would increase risk.

## Similar-looking but semantically different

* Both have `LeaveCommand`, `MessageDelete`, audit, mention, and two-way-message source ancestry. Their deployed guild/channel configuration and bot purpose remain bot-specific; apparent duplicate handlers should not be assumed interchangeable.
* Both read `server.json`, but CDA Pay's independent cog defaults are inconsistent and pay-specific. CDA Admin has a different schema and default set.
* Both discover cogs and expose process lifecycle behavior. CDA Pay loads in `setup_hook` to avoid the duplicate READY loads demonstrated by its log; CDA Admin retains Stage 2's guarded `on_ready` implementation.
* Both write JSON, but CDA Pay partitions pay records by month, stores void/ban state, and creates seven-day application backups. CDA Admin stores moderation/verification state and has no equivalent pay semantics.

## Dependencies and lifecycle

CDA Pay uniquely requires APScheduler and aiofiles for void reset and backups. CDA Admin currently requires only discord.py at runtime. CDA Pay has two cog-owned background systems; CDA Admin has discord.py task loops for status and administration. Neither runs in FastAPI or depends on portal availability. Management manifests currently advertise no embedded management agent; the platform can still distinguish process state, Discord connection/READY, and future heartbeat freshness externally.

## Storage and business boundaries

Keep pay windows, record aggregation, void thresholds/bans, backup naming/retention, payer/trial role rules, embeds, commands, and monthly schemas inside CDA Pay. Keep moderation, verification, announcements, and admin role policies inside CDA Admin. Never point either bot at the other's runtime directory.

## Future candidates and deferred debt

After production characterization, candidates are a small shared server-config loader and authorized atomic JSON repository, but only if schemas/default semantics are made explicit without compatibility branches. Common debt includes direct synchronous JSON I/O in event-loop callbacks, inconsistent command error handling, hard-coded Discord identity/business values, and limited management heartbeat integration. CDA Pay additionally needs a future decision on monthly rollover, DST-safe wall scheduling, persisted missed-job recovery, aggregate edit defects, and concurrent write locking. These are deliberately deferred because changing them now could alter production pay state.
