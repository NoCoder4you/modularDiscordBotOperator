# UNBOT

UNBOT independently watches configured Habbo group members for online/offline
policy milestones, tracks immutable Habbo IDs for newly hidden profiles, and offers
Habbo username suggestions. It is a separate Discord process; it does not share a
client with either CDA bot or require the portal.

## Requirements and installation

- Python 3.11 or newer (the source syntax itself requires 3.10+; 3.11 is the
  monorepo-supported baseline).
- `discord.py>=2.0,<3` and `aiohttp>=3.8,<4`.

From the repository root:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r bots/unbot/requirements.txt
export PYTHONPATH="$PWD/bots/unbot/src:$PWD"
python -m unbot
```

Install test dependencies with `pip install -r bots/unbot/requirements-test.txt`.

## Configuration

| Variable | Required | Meaning |
| --- | --- | --- |
| `UNBOT_TOKEN` | yes | Discord bot token; secret, never commit it |
| `MDBO_RUNTIME_ROOT` | no | Stage 1 runtime root; defaults to `./runtime` |
| `MDBO_LOG_LEVEL` | no | console log level; defaults to `INFO` |
| `HABBO_MOD_ALERT_CHANNEL_ID` | no | initial MOD alert channel ID(s) |
| `HABBO_OOA_ALERT_CHANNEL_ID` | no | initial OOA alert channel ID(s) |

Channel values may contain IDs separated by commas/spaces. Owner-only `setmod` and
`setooa` persist replacements, which take precedence on future starts. Fixed Habbo
group IDs, the notification user ID, and the ID-tracker default channel remain
source-compatible application configuration. Discord privileged intents must be
enabled for the application because the bot requests all intents.

## Data, APIs, and background work

All mutable JSON lives under
`$MDBO_RUNTIME_ROOT/data/unbot/`; `USERS/` contains per-profile time audits. Static
statuses ship in `src/unbot/defaults/statuses.txt`. Runtime data is deliberately not
bundled with the package and must be backed up for deployment.

The status task runs every 15 seconds. Habbo profile and ID tasks run every five
minutes and start exactly once during extension setup. They call public APIs at
`www.habbo.com`; username synonyms also call `api.datamuse.com`. Routine profile
lookups are paced to one per second. The bot needs outbound HTTPS and Discord access.
It has no database, Redis, or platform scheduler.

Shutdown through discord.py, owner `stop`, or process termination closes the bot;
cog unloading cancels polling and closes aiohttp sessions. Use a supervisor that
sends SIGTERM, allows a shutdown grace period, and restarts only this process.
Management-agent reporting remains disabled until the generic supervisor contract is
implemented; reporting failure therefore cannot affect bot operation.

## Testing

```bash
pytest bots/unbot/tests
```

Tests inject Discord/aiohttp doubles. They require no token, network, scheduler run,
or production state. See `docs/migrations/unbot.md` for migration/cutover details and
`docs/migrations/unbot-inventory.md` for authoritative behavioral characterization.
