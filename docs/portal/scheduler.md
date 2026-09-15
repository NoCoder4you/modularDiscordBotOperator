# Scheduler portal

The authenticated Scheduler navigation appears only when at least one visible bot grants `scheduler.view`. List and detail lookups filter by exact-bot authorization; an unauthorized guessed task ID returns the same not-found error as an absent task.

All create, enable/disable, delete, and Run Now routes are POST-only and use the existing synchronizer CSRF token, strict same-origin checks, secure revision-backed session lookup, 4 KiB form limit, security headers, request ID, and safe-error renderer. Backend catalog, bot, permission, parameters, timezone, schedule, bounds, and optimistic revision checks are authoritative. The browser cannot set owner, bot/type on edit, definition version, execution state, or system ownership.

Task detail renders only safe declarative fields and bounded status history. It does not render raw database serialization, internal callback names, tracebacks, paths, credentials, or environment data. Structured scheduler audits distinguish `initiated_by=scheduler` and retain the original `authorized_by` identity as the actor.
