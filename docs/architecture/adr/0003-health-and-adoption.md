# ADR 0003: Evidence-based health and safe adoption

Status: Accepted design; implementation deferred

## Decision

Health separates operator intent, OS process evidence, fresh versioned heartbeat, Discord connected/READY evidence, process instance identity and crash history. PID existence never means Online or ownership. On supervisor restart, query fixed systemd units and correlate invocation/start metadata with heartbeat instance identity; PID files are non-authoritative. Preserve healthy bots and resume journald by cursor. Conflicts/stale evidence become Unknown.

## Consequences

Bots need tiny optional best-effort heartbeat instrumentation. Missing/stale heartbeat reduces management confidence but never stops Discord operation automatically.
