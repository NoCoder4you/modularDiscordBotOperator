# RPA Admin

RPA Admin is the independently managed Discord process for RPA moderation, Habbo motto verification and role reconciliation, raffles/giveaways, pay administration, audit logging, reaction roles, onboarding, and application routing. It is a behaviour-preserving package migration from `NoCoder4you/RPA-Admin` commit `8843a6a978231ed24ecfda269785ea62520ced3d`.

## Requirements and installation

Python 3.11+ is supported (the source syntax requires at least 3.10). Install this bot independently:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r bots/rpa-admin/requirements.txt
```

Runtime dependencies are discord.py 2.x and aiohttp 3.x. Tests additionally require pytest 8.x. The source had no dependency metadata, so conservative API-compatible ranges are recorded rather than claiming an exact source version.

## Configuration and run command

Set the secret `RPA_ADMIN_TOKEN`. `MDBO_RUNTIME_ROOT` defaults to `./runtime`, and `MDBO_LOG_LEVEL` defaults to `INFO`. With the repository root and this bot's `src` directory on `PYTHONPATH`:

```bash
PYTHONPATH="$PWD:$PWD/bots/rpa-admin/src" python -m rpa_admin
```

The bot uses prefix `RPA ` and all Discord intents. Enable the privileged intents in the Discord developer portal. Application commands are global and retain the owner-only `RPA sync` workflow. Discord IDs, group mappings, and business settings are JSON/constants, not secrets.

## Runtime data

All JSON mutations are isolated below `${MDBO_RUNTIME_ROOT}/data/rpa-admin/`; logs are written below `${MDBO_RUNTIME_ROOT}/logs/rpa-admin/`. Sanitized static defaults are copied on first access. Production `VerifiedUsers.json`, active `raffles.json`, giveaways, pay state, restrictions, reaction roles, sterile-channel state, mute state, and alert state must be restored during cutover; they are intentionally not committed as defaults. Paths are CWD-independent and traversal is rejected.

Verification uses Habbo public profile and group endpoints. A user proves control by placing a five-minute eight-character challenge in their motto; successful mappings retain the list-of-objects JSON schema. Existing users resync their stored identity, and staff can use `RPA forceverify`. DNH/BoS restrictions remain enforced. External calls require network access at runtime but tests mock them.

Raffles remain staff-managed by the `Rank Seller` role. Entries persist across restart; weighted unique winner drawing closes the raffle and announces a present winner by Discord mention or otherwise by the persisted entrant/Habbo label. Giveaways are a separate self-entry button workflow.

## Tests and deployment

```bash
pytest bots/rpa-admin/tests
```

Tests use fakes, temporary paths, and patched API entry points; they require no Discord token or connection and no live Habbo request. Install and run RPA Admin as its own service/process. Do not embed it in another bot, the portal, or FastAPI. See `docs/migrations/rpa-admin.md` for state cutover and rollback.
