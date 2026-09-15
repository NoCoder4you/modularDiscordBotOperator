# Process identity and restart recovery

Each execution receives a random `process_instance_id`, distinct from stable `bot_id`. The durable
record contains only bot ID, instance ID, PID, UTC start time, Linux `/proc/<pid>/stat` kernel start
ticks, the observed argv, and process state. It contains no environment or secret values.

PID is never authoritative. Before signaling a process, the supervisor requires both kernel start
ticks and the entire observed argv to equal the recorded evidence. On startup it applies the same
check to a record: a live exact match is conservatively adopted as `running`; dead records are
dropped; an existing PID with conflicting evidence is retained as `unknown`, never adopted,
terminated, or overwritten by a new start.

The state document is versioned JSON at a caller-selected trusted path. Writes use a mode `0600`
exclusive temporary file, flush/fsync, atomic replace, and parent-directory fsync. Missing,
malformed, or unsupported-version files safely yield no adoption. State is evidence for the
development adapter—not a PID-file ownership claim.

Production recovery follows ADR 0003 instead: fixed systemd unit/cgroup/invocation evidence will be
correlated with a future heartbeat instance ID. The Stage 7 subprocess evidence is intentionally
more conservative: after adoption it can safely signal a proven process but cannot recover lost
stdout/stderr pipes. Unknown evidence requires operator investigation or authoritative systemd
reconciliation.
