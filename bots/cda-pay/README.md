# CDA Pay

CDA Pay is the independently runnable Discord process for pay records, summaries, voids/bans, application backups, auditing, and message relay. It does not share a Discord client or lifecycle with CDA Admin or the portal.

## Runtime

Use Python 3.11 (the monorepo baseline). From the repository root:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r bots/cda-pay/requirements.txt
PYTHONPATH=bots/cda-pay/src:. python -m cda_pay
```

`CDA_PAY_TOKEN` is required and must be supplied in the process environment. `MDBO_RUNTIME_ROOT` defaults to `./runtime`; `MDBO_LOG_LEVEL` defaults to `INFO`. Do not place tokens in `bot.toml` or `server.json`.

## Configuration and state

On first cog load, `runtime/data/cda-pay/JSON/server.json` is created. Configure its channel snowflakes (`admin_stats`, `paystat_allowed`, `payvoid_allowed`, `audit_log`, `backup_notifications`, `mention_log`), role names (`payer`, `trial_payer`, `stat_edit`), target user, and backup/void-reset timezone/hour/minute. Some source rules intentionally remain hard-coded (`Foundation`, `Payer`, `Stat Edit`, the owner/relay user, and relay guild); see the migration inventory before changing them.

Mutable files are isolated below `runtime/data/cda-pay/`: monthly `JSON/<MON_YEAR>.json`, `JSON/CDAVoidData.json`, `JSON/server.json`, and application-created `BACKUPS/*.json`. Copy production state into this location only while the old process is stopped. The package contains no production JSON.

Pay dates/windows use `Europe/London`, including GMT/BST. External date keys remain `YYYY-MM-DD`; month filenames remain uppercase abbreviated month/year. The void scheduler runs every Sunday at the configured wall time. The backup loop waits for that configured London time and then repeats every 24 hours. Both schedulers are in-process and CDA Pay must have exactly one running instance.

The entry point loads cogs once in `setup_hook`, so reconnect READY events do not duplicate extensions. Cog unload cancels the backup loop and shuts down APScheduler. stdout structured logs identify `bot=cda-pay`; generated log files are not committed.

## Tests and deployment

```bash
python -m pytest bots/cda-pay/tests
```

Tests are offline and use temporary runtime roots; they require no token or Discord connection. For deployment, install this requirements file in an isolated environment, set `PYTHONPATH` as above (or install the package path), configure secrets via the service manager, grant write access to the runtime root, and use SIGTERM/process supervision for clean shutdown. Keep CDA Admin as a different process. Follow `docs/migrations/cda-pay.md` for state cutover and rollback.
