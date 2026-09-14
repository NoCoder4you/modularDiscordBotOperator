# ADR 0004: Portal is an authenticated typed control client

Status: Accepted design; implementation deferred

## Decision

The portal authenticates users, enforces deny-default per-feature/per-bot authorization, renders evidence and calls typed supervisor operations. It never imports bot business/Discord packages, owns processes, accepts shell/stdin/module/PID/path input, browses files, stores secrets, or equates running with healthy. Sensitive actions use operation IDs and audit events.

## Consequences

Portal implementation waits for supervisor/health contracts. Console is read-only and typed configuration/data resources require allow-lists and schemas.
