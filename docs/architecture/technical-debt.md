# Technical-debt register

| Severity | Issue | Affected components | Risk | Recommended action | Stage |
|---|---|---|---|---|---|
| BLOCKER | `src/` bot packages lack install metadata/declared launch environment; manifest CWD does not make them importable | all bots, manifests | supervisor launch is environment-dependent or broken | package/install each bot and define fixed interpreter selection; test from unrelated CWD | 7 |
| BLOCKER | manifest does not fully define deterministic process launch/timeout | manifest, supervisor | wrong environment and unsafe stop assumptions | add only proven interpreter/environment selector and shutdown timeout; trusted-path catalog | 7 |
| HIGH | no heartbeat/instance identity or evidence reconciler | all bots, state, supervisor | PID can be mistaken for healthy/owned bot | minimal best-effort versioned heartbeat and state reconciliation | 8 |
| HIGH | graceful shutdown/task/scheduler cleanup inconsistent | CDA Admin, UNBOT, RPA Admin | lost writes, leaked sessions, forced kills | characterize SIGTERM; add minimal lifecycle hooks without business changes | 7–8 |
| HIGH | most critical JSON writes are direct/non-atomic and may race | all bot state, especially pay/verification | corruption or lost updates | inventory locks; migrate proven stores to bot-owned atomic transactions with tests | 8/13, not Stage 6 |
| HIGH | runtime containment is logical, not OS isolation | runtime/deployment | compromised bot reads/writes peer data | separate Unix users and 0700 roots; narrow supervisor/backup access | 17 |
| HIGH | broad unpinned dependency ranges | all environments | non-reproducible deploy/ARM breakage | per-environment ARM64-tested lock inputs | 7/16 |
| MEDIUM | mixed `print`, structured logger, logger names and streams | all bots, especially RPA Admin | poor correlation/redaction/console quality | capture legacy output; gradually normalize infrastructure logging | 9 |
| MEDIUM | `MDBO_RUNTIME_ROOT=./runtime` depends on CWD | config | data placed unpredictably | require absolute production value; validate deployment | 7/17 |
| MEDIUM | `management_agent` manifest flag is ambiguous and unused | manifests | misleading capability decisions | deprecate; negotiate protocol capability explicitly | 7–8 |
| MEDIUM | in-memory schedulers lack uniform catch-up/duplicate-run policy | bot schedulers | missed/duplicate business jobs after restart | document each job and add bot-specific idempotence where required | later bot-specific work |
| MEDIUM | tests do not cover real clean launch, signals, adoption, crash loops or authorization | platform | lifecycle/security regressions | fake-process and security integration layers | 7–10 |
| LOW | module-level Discord clients/config side effects make import probing awkward | all bots | tooling cannot import entry modules without side effects | validate specs/package resolution without importing `__main__`; defer factories unless needed | 7/defer |
| LOW | direct static IDs remain in source | bot business code | operational changes require code deploy | move only demonstrably deployment-specific IDs into typed bot config | 13 |
| DEFER | similar cog loading and command management code | bot entry modules | duplication only | abstract only after authenticated management semantics are proven | 15 |
| DEFER | generic raw JSON portal editing | portal/data | high corruption/security risk | do not build; prefer typed workflows | indefinite |
# Stage 12 deliberately deferred debt

- Implement and deploy the private, instance-authenticated local `BotControlAdapter` transport.
- Add a shared bot-side maintenance enforcement component before enabling maintenance capabilities.
- Replace the development subprocess backend with the accepted systemd/D-Bus/polkit backend.

## Stage 13 deferred resource contracts (2026-09-15)

The canonical audit and prerequisites are in `docs/portal/configuration-and-data.md`. CDA Pay payroll/void files, UNBOT histories/state, RPA Admin verification/moderation/workflow stores, and CDA Admin security/mixed-state files remain deferred. Risks include lost payroll, identity, authorization, and workflow state. Prerequisites are bot-owned schemas, coordinated atomic/transactional writes, typed business operations, and recovery tests. Full backups, SQLite bot adapters, resource-specific grants beyond bot scope, and hot reload also remain debt.
