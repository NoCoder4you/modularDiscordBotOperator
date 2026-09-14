# Architecture decisions

## Decisions

1. **Process isolation is non-negotiable.** Four Discord clients will run as four OS processes. The portal and supervisor are separate lifecycles.
2. **Typed supervisor boundary.** The `Supervisor` protocol exposes only `status`, `start`, `stop`, and `restart` by validated bot ID. It exposes neither a shell nor filesystem browsing. A future implementation must use argument arrays with `create_subprocess_exec`/`shell=False`, process groups, graceful timeouts, generation counters, and captured streams.
3. **Declarative, secret-free TOML manifests.** A strict `[bot]` schema rejects unknown fields, traversal, invalid IDs, malformed entry points, and token/secret keys. All four are disabled/manual until migrated.
4. **Independent status signals.** `BotStatus` stores process existence, gateway connection, READY, and heartbeat separately. Its visible state supports online, starting, restarting, disconnected, crashed, crash loop, maintenance, disabled, offline, and unknown.
5. **Isolated runtime roots.** `RuntimePaths` builds only under `data/<validated-bot-id>` and rejects paths which resolve outside that root. Source trees contain no runtime data.
6. **Immutable configuration.** Environment parsing creates frozen configuration rather than module globals. Platform settings, manifest metadata, secret environment variables, and runtime state are separate concerns.
7. **Logging to stdout first.** Bot-scoped, timestamped records suit supervisor collection and avoid duplicate handlers. Rotation belongs at the deployment/supervisor layer; secret values are never accepted by logging setup.
8. **Atomic durable JSON.** Shared writes use a same-directory temporary file, flush/fsync, and atomic replace. Callers must first obtain an authorized bot-scoped path. Cross-process locking and schema-specific concurrency remain future concerns.
9. **Minimal shared core.** Only proven infrastructure primitives exist. Discord.py is not a shared-core or portal dependency. Commands and business logic stay bot-owned.
10. **Migration-friendly dependencies.** Root `pyproject.toml` owns platform tooling. The reference requirements remain intact, and migrated bots may have separate dependency sets.
11. **Minimal portal.** FastAPI supplies liveness only. Management APIs wait for authentication, backend authorization, audit logging, and a real injected supervisor.

## Trust boundaries

The browser is untrusted. Future privileged API requests require authenticated identities and server-side authorization. The portal selects a known manifest by validated ID and requests a typed action. Only the supervisor creates processes. Manifests cannot carry secrets; child processes receive only their bot-specific secret and paths. Data/config APIs must use allow-listed resources rather than arbitrary paths.

## Lifecycle and telemetry

A PID means only `process_running`. `online` requires independent Discord readiness and a fresh management heartbeat. A future heartbeat payload should include bot ID, generation, monotonic sequence, gateway/READY flags, timestamp, and sanitized health details. The supervisor owns PID and generation truth.
