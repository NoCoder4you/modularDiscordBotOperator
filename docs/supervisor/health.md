# Health evidence and process correlation

Health keeps desired state, process existence, verified identity, heartbeat presence/freshness,
Discord connection, Discord READY, maintenance acknowledgement, unexpected exit, and crash-loop
evidence independently. A heartbeat is accepted only for a catalog bot whose current process
identity is verified and whose UUID matches; its sequence must exceed the last accepted sequence.

Production evidence is behind `SystemdEvidenceAdapter`: callers provide only a canonical bot ID,
which maps internally to one of four fixed units. Its injected D-Bus-compatible transport returns
typed active/sub-state, MainPID, InvocationID, cgroup, and optional journal cursor evidence. There
is no arbitrary unit, path, argv, shell, or `systemctl` interface. Identity requires matching bot,
unit, positive PID, invocation, and cgroup; PID alone cannot verify or authorize action.

On supervisor restart, durable Stage 7 records are rechecked first and health begins without a
heartbeat (`Starting` within grace, then `Unknown`). Only a fresh matching heartbeat restores
application health. Dead, reused-PID, invocation/cgroup-mismatched, or missing metadata remains
unverified and causes no kill, restart, or adoption. An independently systemd-restarted bot may be
adopted only after the fixed unit, invocation, cgroup and current instance UUID correlate; prior
heartbeats are discarded. The cursor field is only a future journald recovery foundation.

Stage 7 has no automatic restart policy or crash counter, so Stage 8 does not invent one. It
models a crash-loop latch for the future authoritative policy; no automatic restart occurs and
manual lifecycle operations remain the recovery boundary.
