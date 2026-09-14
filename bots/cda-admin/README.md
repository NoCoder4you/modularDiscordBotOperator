# CDA Admin

CDA Admin is the independently runnable Discord administration, moderation, Habbo
verification and role-management bot migrated from `NoCoder4you/CDA-Admin`. It does not
run in the portal and does not share a Discord client with another bot.

## Requirements and setup

The source was developed with Python 3.10, but the migrated package requires **Python
3.11+** because it uses the Stage 1 `shared.bot_core` runtime infrastructure. From the
monorepo root, create an isolated environment and install only this bot's dependencies:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r bots/cda-admin/requirements.txt
```

Set the Discord token outside source control. The other settings have safe defaults:

```bash
export CDA_ADMIN_TOKEN='replace-locally'
export MDBO_RUNTIME_ROOT="$PWD/runtime"  # default: ./runtime
export MDBO_LOG_LEVEL=INFO                # DEBUG/INFO/WARNING/ERROR/CRITICAL
```

The application requests all Discord intents; enable the required privileged intents for
this application in the Discord developer portal. It performs no automatic slash-command
sync: the owner-only prefix command `noah sync` preserves the original registration flow.

## Run independently

From the monorepo root:

```bash
PYTHONPATH="$PWD/bots/cda-admin/src:$PWD" python -m cda_admin
```

The shell's current working directory does not affect packaged cog or status discovery.
Relative `MDBO_RUNTIME_ROOT` intentionally remains relative to the launching process, so a
production service should set it explicitly (preferably absolute) and keep it stable.

Mutable state is isolated at `$MDBO_RUNTIME_ROOT/data/cda-admin/`. On first use, sanitized
schema-compatible defaults are created. A production deployment must use the documented,
backed-up cutover process to copy current `admins.json`, `niceblock_users.json`,
`punishment.json`, `rolesbadges.json`, `server.json`, and `verification_codes.json`.
Do not copy the source snapshot blindly: it contains production-shaped user records.
Logs go to stdout for supervisor capture and are not written into the source tree.

## Test

Install test dependencies and run from the monorepo root:

```bash
python -m pip install -r bots/cda-admin/requirements-test.txt
pytest
```

The tests use temporary runtime directories and fake Habbo responses. They require no bot
token, Discord connection, live filesystem, or external API. Deployment remains disabled
and manual in `bot.toml` until cutover validation is complete.
