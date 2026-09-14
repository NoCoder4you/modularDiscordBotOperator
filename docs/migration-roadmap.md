# Migration roadmap

1. **Stage 1 — Platform foundation:** audit, contracts, safe primitives, manifests, minimal portal, tests, and documentation.
2. **Stage 2 — Migrate CDA Admin:** preserve behavior in an independent package/process; characterize configuration, dependencies, data, cogs, and lifecycle with offline tests.
3. **Stage 3 — Migrate CDA Pay.**
4. **Stage 4 — Migrate UNBOT.**
5. **Stage 5 — Migrate RPA Admin.**
6. **Stage 6 — Extract proven shared functionality:** extract only repeated, compatible patterns evidenced by migrated bots.
7. **Stage 7 — Supervisor/process management:** implement safe argv-based lifecycle, signals, generations, crash-loop policy, stream collection, and heartbeat ingestion.
8. **Stage 8 — Web management features:** authenticated/authorized APIs and progressively enhanced UI through the supervisor boundary.
9. **Stage 9 — Backups, scheduler, configuration and deployment management:** allow-listed resources, atomic operations, audit trails, and restore testing.
10. **Stage 10 — Raspberry Pi production deployment and hardening:** service manager integration, OS users/permissions, rotation, monitoring, recovery, and deployment runbooks.

No later stage begins implicitly. In particular, Stage 2 migrates only CDA Admin and does not extract speculative common business logic.
