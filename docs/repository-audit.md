# Existing repository audit (Stage 1)

Audit performed before foundation changes against every tracked source/configuration file.

## What exists

`discord-bot/` is a small generic, public multi-server discord.py foundation—not identifiable as CDA Admin, CDA Pay, UNBOT, or RPA Admin. `bot.py` constructs one `commands.Bot`, enables guild/member intents, discovers uppercase `COGS/*.py`, syncs slash commands, records lifecycle events, and closes gracefully. `COGS/core.py` contains guild-only `/ping`, `/botinfo`, and `/serverinfo` commands.

Configuration is a frozen dataclass loaded with python-dotenv. It validates a required generic `DISCORD_TOKEN` and optional positive guild/owner IDs. Dependencies are two unpinned lower bounds (`discord.py>=2.5.0`, `python-dotenv>=1.0.0`). Its local environment example contains placeholders only.

`UTILS/data_manager.py` validates guild IDs and simple JSON names, uses per-path asyncio locks, writes via temporary-file replacement, and separates guilds beneath `DATA/guilds`. `UTILS/logger.py` creates console and rotating-file root handlers and guards against duplicate handlers. `DATA` and `LOGS` contain only tracked structure files. Root and nested gitignores cover common secrets, logs, databases, caches, guild runtime data, and temporary files.

## Reusable strengths

- Frozen validated configuration and fail-fast startup.
- Deterministic cog discovery and isolated extension-load failure reporting.
- Guild-ID data separation, traversal checks, async in-process serialization, and atomic replacement.
- UTC-aware startup timestamps and useful lifecycle logging.
- Duplicate-handler checks and rotation awareness.

These are evidence for shared *concepts*. The original implementations remain untouched until a bot migration proves compatibility.

## Risks and migration work

- The reference bot is one process with a generic token; it is not a multi-bot manager and must not become one.
- Cog load exceptions are logged and startup continues, potentially yielding a deceptively healthy but incomplete bot. Future readiness must report degraded load state.
- Slash commands sync on every startup and may cause delay/rate-limit risk. This needs per-bot migration review.
- The member intent requires Discord Developer Portal approval/configuration. Text prefix exists while message-content intent is disabled.
- Existing logging mutates the root logger, writes inside the source tree, and can conflict with a future supervisor. Log messages include guild names and raw exception text; a redaction/privacy policy is still needed.
- Async JSON file I/O blocks the event loop; locks are process-local, grow without eviction, and the fixed `.tmp` name is unsafe across processes. There is no schema/versioning, backup, permission hardening, or recovery policy.
- Existing runtime data is source-adjacent and only guild-isolated, not bot-isolated. It must be mapped into the CDA Admin private runtime root only after ownership is confirmed.
- Broad cog-load catching is intentional resilience but can hide required feature failure. Command errors may expose exception detail to logs.
- Dependency ranges are not reproducibly locked and supported upper bounds are unknown. No original tests, CI, packaging metadata, or root README existed.
- `.env.*` protection was nested rather than root-wide; root rules now cover it. Placeholder values must never be interpreted as usable secrets.

## Disposition

Preserve `discord-bot/` unchanged as a runnable reference and source of migration lessons. Do not call it a shared core or bot template yet: it mixes Discord startup, generic commands, root logging, configuration, and source-local persistence. During CDA Admin migration, compare behavior rather than copying it wholesale. Promote only genuinely shared infrastructure after at least two bots demonstrate the same requirement.
