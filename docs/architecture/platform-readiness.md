# Platform readiness assessment

Reviewed 2026-09-14 against implementation, migration documents, tests, and the contracts in [platform-architecture.md](platform-architecture.md).

| Category | Rating | Evidence / remaining work |
|---|---|---|
| Manifests | **NOT READY** | IDs and validation are strong, but fixed executable/environment and stop timeout are absent; `working_directory` cannot expose `src/` packages. |
| Independent execution | **NOT READY** | code/package boundaries are independent, but clean launch requires installation or ad-hoc `PYTHONPATH`; formalize it in Stage 7. |
| Process isolation | **READY WITH MINOR WORK** | no cross-bot imports/clients; OS user isolation is deployment work. |
| Graceful shutdown | **READY WITH MINOR WORK** | discord.py closes on normal signals and CDA Pay has explicit cleanup; scheduler/task behavior needs fake-process and bot-specific characterization. |
| Health reporting | **NOT READY** | state types exist; no bot heartbeat, instance identity, freshness ingestion, or reconciler exists. |
| Logging | **READY WITH MINOR WORK** | shared UTC/bot-ID formatter exists, but prints/logger adoption, stream semantics, redaction, rotation and bounds are incomplete. |
| Configuration | **READY WITH MINOR WORK** | token/runtime/log inputs are explicit process environment; absolute production runtime and typed business-config boundary remain. |
| Secrets | **READY WITH MINOR WORK** | four token names and ignore rules are correct; production systemd credential/env injection and redaction are not implemented. |
| Runtime paths | **READY WITH MINOR WORK** | validated per-bot roots and authorized writes exist; many direct writes and shared Unix identity weaken adversarial isolation. |
| Persistent state | **NOT READY** | resources are isolated and characterized, but critical stores often lack atomicity/locking/schema and safe management contracts. This does not block basic lifecycle supervision. |
| Shared core | **READY WITH MINOR WORK** | small and business-neutral; state/manifest contracts need Stage 7–8 refinement. |
| Tests | **READY WITH MINOR WORK** | broad characterization suite exists; no process lifecycle/adoption/crash-loop/security integration suite yet. |
| Security | **NOT READY** | primitives are promising; auth, control-channel security, OS isolation, archive/log defenses and acceptance tests await their stages. |
| Raspberry Pi deployment | **NOT READY** | compatible baseline is documented but locks, users, permissions, systemd/polkit, storage and runbooks do not exist. |
| Supervisor readiness | **NOT READY** | Protocol only; launch contract blockers must be resolved as the first part of Stage 7. |
| Portal readiness | **BLOCKED** | liveness-only portal is correct; privileged portal work must wait for supervisor, health, authentication/authorization and audit contracts. |

## Four-bot isolation result

Each bot owns a distinct Discord client, package, token and data-root ID. No bot imports a peer, portal, or supervisor. A bot/portal failure can be isolated. Restarting an eventual systemd-backed supervisor need not interrupt bots. RPA Admin is a fourth peer process—the diagram layout must not imply it is a child of UNBOT.

## Pre-supervisor prerequisites

Only these are blocking Stage 7 lifecycle implementation:

1. deterministic installation/import and a fixed non-shell launch specification for every `src/` package;
2. a strict catalog resolving trusted repository paths and interpreter/environment selection;
3. an explicit graceful shutdown timeout/default.

Heartbeat, consistent logging, atomic business stores, portal authentication, OS users, systemd units and deployment locks are important but are sequenced after or within the supervisor foundation; they do not justify modifying bot business behavior now.

## Validation and integrity

Stage 6 makes documentation/README changes only. Test commands and exact results are recorded in the commit/final report after execution. Migration snapshots must show no working-tree changes. No production supervisor or portal functionality is part of this stage.

## Stage 6 validation results

* `pytest`: 160 passed, 6 skipped in 2.24 seconds on Python 3.14.4. Shared/platform, UNBOT, and available RPA Admin/CDA tests passed. Three CDA Admin Discord-dependent modules, one CDA Pay Discord-dependent module, and two CDA Pay APScheduler-dependent cases were skipped because those optional bot runtime dependencies are not installed in the platform environment. This is an environment coverage warning, not a failing behavior test.
* `ruff check .`: failed on 46 pre-existing findings in migrated implementation and immutable migration snapshots (unused imports, import ordering, unnecessary f-strings, and unused locals). Stage 6 deliberately did not alter bot behavior or snapshots to perform lint cleanup.
* Strict manifest load and package/`__main__` spec resolution: all four passed when each declared `src` root was explicitly supplied, confirming modules exist and also demonstrating the documented clean-launch packaging gap.
* `python -m compileall -q shared supervisor portal`: passed.
* `git status --short -- migration-sources`: empty; snapshots unchanged.
