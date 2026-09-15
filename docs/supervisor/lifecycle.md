# Process lifecycle contract

## States

The process-only states are `disabled`, `offline`, `starting`, `running`, `stopping`, `restarting`,
`crashed`, and `unknown`. `running` means that an identified OS process survived the startup grace
period. It does not claim Discord connectivity, readiness, heartbeat freshness, or application
health. Disabled is administrative manifest intent, not a synonym for stopped or maintenance.

## Operations and idempotency

Every accepted mutation gets a UUID operation ID and requested/started/completed timestamps,
action, status, optional actor, and stable error category. Results include previous/current process
state and the process instance ID.

* **Start:** validate catalog membership and enabled status; reject an existing or uncertain
  instance; require the named token and executable; create the isolated runtime directory; launch
  fixed `[executable, "-m", entry_point]`; establish kernel identity after a short startup grace;
  report immediate exits as `startup_failed`.
* **Stop:** reject offline state; revalidate identity; mark the exit expected; send SIGTERM; wait the
  manifest timeout; revalidate identity and use SIGKILL only after timeout. A completed escalation
  succeeds with `forced=true`; failure to prove identity yields `process_identity` and never signals
  the uncertain PID.
* **Restart:** hold one lock for the whole stop-confirm-start sequence. A running process is marked
  restarting, the old instance is fully stopped, and a new UUID identifies the replacement.

`start(running)` is `already_running`; `stop(offline)` is `already_stopped`; disabled start is
`disabled`; malformed or unregistered IDs are `unknown_bot`. If another same-bot operation owns the
lock, any start/stop/restart is rejected as `operation_in_progress`, preventing queued stale intent
and overlapping restarts. Locks are per bot, so operations for different bots proceed concurrently.

Unexpected non-zero and zero exits both become `crashed`; a requested graceful or forced exit
becomes `offline`; an exit during the startup grace is `startup_failed`. No automatic restart exists
in Stage 7, so it cannot create a crash loop. Systemd start limits and durable restart policy remain
required before enabling automatic recovery.
