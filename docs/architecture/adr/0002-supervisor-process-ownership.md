# ADR 0002: systemd owns production processes; supervisor owns policy

Status: Accepted design; implementation deferred

## Decision

On Raspberry Pi/Linux, systemd owns one named unit per bot plus supervisor and portal. The supervisor invokes only typed operations on registered units through narrowly authorized D-Bus/polkit. It owns catalog validation, operations, health reconciliation, restart/crash-loop policy and bounded log access; it never exposes shell or arbitrary PID/argv operations. A subprocess backend is permitted for tests/development.

## Consequences

Bots survive portal/supervisor restart and can be identified by unit/cgroup/invocation metadata. Restart responsibilities and rate limits must be coordinated. Production unit/polkit implementation is deferred.
