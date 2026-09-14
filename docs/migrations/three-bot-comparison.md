# Three-bot architectural comparison

This comparison follows independent migrations of CDA Admin, CDA Pay, and UNBOT. It
supersedes neither their inventories nor the Stage 3 two-bot comparison.

| Concern | CDA Admin | CDA Pay | UNBOT |
| --- | --- | --- | --- |
| Process/client | independent `commands.Bot` | independent `commands.Bot` | independent `commands.Bot` |
| Secret | `CDA_ADMIN_TOKEN` | `CDA_PAY_TOKEN` | `UNBOT_TOKEN` |
| Entry module | `cda_admin` | `cda_pay` | `unbot` |
| Cogs | packaged dynamic discovery | packaged dynamic discovery | packaged dynamic discovery |
| Data root | `data/cda-admin` | `data/cda-pay` | `data/unbot` |
| Persistence | several bot schemas | pay/void schemas | watcher/ID JSON schemas |
| Background work | moderation/announcement jobs | pay-specific behavior | three status/API polling loops |
| External API | Habbo/Discord behavior | Habbo/Discord behavior | Habbo, Datamuse, Discord |
| Dependencies | discord.py, aiohttp, APScheduler | discord.py, aiohttp | discord.py, aiohttp |
| Time semantics | bot-specific | pay/timekeeping-specific | aware UTC elapsed policy |
| Management | generic contract ready, agent off | same | same |

## Confirmed common infrastructure

All three genuinely use Stage 1 `PlatformConfig`, `RuntimePaths`, manifest validation,
stable bot IDs, per-bot data isolation, and supervisor-friendly logging. Each is an
independent module/process with environment-only token loading. These generic pieces
contain no command, role, payment, moderation, or inactivity policy. Atomic JSON is
shared where callers already use the same authorized-path semantics; legacy schema
write behavior was not forcibly homogenized.

## Possible later common infrastructure

Package-aware cog discovery/setup, graceful signal/lifecycle wrappers, generic
heartbeat publication, and an optional bounded HTTP/rate-limit primitive recur in at
least two bots. They should be evaluated in a dedicated refactor only after lifecycle
and failure-semantics tests prove equivalence. A convenience JSON repository may be
useful, but only if it preserves each bot's malformed-file defaults, atomicity, key
normalization, and error boundaries rather than adding compatibility switches.

## Bot-specific business behavior

CDA Admin moderation, verification, announcements, roles, and permissions remain
there. CDA Pay pay recording, timekeeping, voiding, auditing, and schemas remain
there. UNBOT's MOD/OOA roster precedence, inactivity clocks/milestones, mention-at-
deadline rule, recovery/history tracking, fixed IDs, Habbo failure escalation,
profile-hidden tracking, and username suggestion behavior remain wholly under
`unbot`. Their embeds, strings, commands, authorization rules, schedules, and state
schemas are not shared infrastructure.

## Similar-looking code deliberately left separate

The bots all load cogs, rotate statuses, call Habbo/Discord, write JSON, and close
clients. Those similarities are insufficient where timing, retry, normalization,
failure, authorization, and persistence semantics differ. UNBOT's one-second shared
API gate and five-minute polling are not CDA scheduling. CDA Pay time calculations
are not UN offline policy. CDA Admin role checks are not UN group membership. Local
cog setup and bot-specific aiohttp sessions therefore remain separate during Stage
4; no compatibility-heavy shared core or platform-wide scheduler was introduced.
