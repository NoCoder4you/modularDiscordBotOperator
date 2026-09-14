# ADR 0005: Separate secrets, deployment configuration, business config and state

Status: Accepted design; implementation deferred

## Decision

Inject each bot token via systemd credentials or a protected environment file into only that bot. Secrets never enter manifests, portal state, argv, logs, status or audit. Deployment settings use environment/manifests; business configuration stays bot-owned and is later exposed only through typed schemas; runtime state remains under per-bot roots. Use atomic, locked, resource-specific changes and backups rather than a generic JSON editor.

## Consequences

Some source Discord IDs intentionally remain. Portal editing requires explicit resource contracts and cannot be inferred from files.
