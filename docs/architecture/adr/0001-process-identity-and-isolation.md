# ADR 0001: Canonical identity and four isolated bot processes

Status: Accepted (Stage 6)

## Decision

Use canonical IDs `cda-admin`, `cda-pay`, `unbot`, and `rpa-admin`, validated as lowercase kebab-case and then against a manifest catalog. Each bot is a separate process, Discord client, environment and preferably venv/Unix account. IDs are single logical keys, never paths or shell fragments. Runtime data is `data/<id>` and logs are `logs/<id>` below a trusted relocatable root.

## Consequences

Displays and Python underscore package names remain distinct. Failures/restarts isolate cleanly. Extra venvs/users cost disk and deployment work. Shared path helpers do not replace OS permissions.
