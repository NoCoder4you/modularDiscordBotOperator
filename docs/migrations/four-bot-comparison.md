# Four-bot implementation comparison after Stage 5

This comparison is based on the migrated CDA Admin, CDA Pay, UNBOT, and RPA Admin implementations and updates the two-/three-bot findings. It describes evidence, not a mandate for immediate extraction.

| Concern | CDA Admin | CDA Pay | UNBOT | RPA Admin |
|---|---|---|---|---|
| Process/startup | own `commands.Bot`, module entry | own bot/module entry | own bot/module entry | own all-intents bot/module entry |
| Config/environment | explicit token/platform config | explicit token/platform config | explicit token config/path wrapper | explicit token/platform config |
| Cogs | packaged dynamic extensions | packaged extensions | packaged extensions | 22 packaged dynamic extensions |
| Storage | isolated JSON; shared safe primitives where adopted | isolated JSON/business record helpers | isolated JSON with bot-specific paths | isolated JSON, many schema-specific stores |
| External services | Habbo/Discord | Discord/pay policy | Habbo public API | Habbo stdlib plus paced aiohttp/Discord |
| Scheduling | role/background work | pay schedulers | profile/inactivity loops | status, autoroles, mute/pay/giveaway loops |
| Lifecycle | independent clean close | independent clean close | independent clean close | independent clean close/session unload |
| Permissions | moderation/business-specific | finance/business-specific | owner/role policy | Discord decorators, owner/admin and named-role policy |
| Management | established contracts only | established contracts only | established contracts only | future-compatible stdout/process boundary; no new contract |

## Confirmed shared infrastructure

* `PlatformConfig`, bot-ID validation, `RuntimePaths`, `AuthorizedPath`, logging setup, manifest validation, and management state contracts are genuinely cross-bot infrastructure. All four require token/environment validation, isolated data/log roots, a stable ID, independently launchable module, and observable process/Discord readiness.
* The manifest schema works unchanged for four independent clients: package entry point, relative working directory, disabled/manual-safe migration default, presentation metadata and management-agent capability.
* Runtime trust boundaries and traversal rejection are common security behaviour. They contain no bot policy and materially reduce cross-bot state risk.
* Generic atomic JSON replacement is already proven useful for bot state where callers can supply authorized paths. It must remain opt-in while legacy schemas/error semantics are characterized.

## Strong shared-infrastructure candidates

* A small extension discovery/loading helper could serve CDA Admin and RPA Admin (and possibly others) if it accepts a package, deterministic ordering/error callback, and never encodes bot names or load-failure policy.
* Idempotent logging initialization with bot identity, stdout and isolated file destinations is duplicated operational plumbing and could reduce duplicate handlers after reloads.
* Lifecycle helpers for one-time loop start, cancellation, client-session closure, and non-fatal telemetry are common, provided each bot retains task timing/error policy.
* Safe JSON read and atomic replacement primitives are strong candidates, but adapters must preserve each file's missing/malformed defaults, backup rules, formatting and concurrency expectations. A blanket store class is not yet justified.
* A bounded HTTP session owner (timeouts and close only) may be reusable between real aiohttp consumers. Retry, response validation, caching, pacing and 429 policy must remain injected because bots differ.

## Possible future abstractions

* Declarative environment fields beyond token/root/log level, a common READY/heartbeat reporter, deterministic cog-load reports, and shared test fakes may be useful in the next architecture phase.
* Async file locks and schema-neutral state transactions could reduce lost updates after every affected schema receives characterization tests.
* Standard signal orchestration could make supervisor termination consistent. Do not implement the supervisor or portal control plane until the separate architecture review.
* Discord command error presentation has structural similarity but messages and escalation policy differ enough that only low-level formatting may eventually be generic.

## Similar-looking code that is semantically different

* Habbo access is not one client policy: CDA Admin role verification, UNBOT identity/profile monitoring, and RPA verification/online-time/adaptive role maintenance have different endpoints, timing, failure meaning, and rate-limit behaviour.
* CDA Pay scheduling/pay records and RPA pay announcement/pay-void rules differ in schema, guild scope, time windows, thresholds and authorization despite similar names.
* Each bot's path wrapper preserves legacy filenames/defaults. The shared trust boundary is common; the wrappers are compatibility/application code.
* Background loops differ in destructive risk, pacing, catch-up and reconnect semantics. A single generic scheduler would hide policy.
* Permission checks that all inspect Discord roles/permissions are not interchangeable: owner IDs, Administrator/Manage Roles/Manage Guild decorators, named `Rank Seller`, finance roles and UN policy encode distinct authority.
* JSON stores share mechanics but treat malformed files differently (empty fallback, reset, corrupted backup, or normalized rows). Uniform error behaviour would be a behavioural change.

## Business logic that must remain bot-specific

RPA motto verification, restrictions, badge hierarchy, username approval, raffle weighting/announcement text, giveaway eligibility, moderation messages and Discord IDs remain in `rpa_admin`. CDA Admin moderation/role policy, CDA Pay timekeeping/void rules, and UNBOT identity/inactivity policy remain in their packages. Embeds, command implementations, bot-specific schemas and permission rules are not shared infrastructure.

## Recommendation for the next phase

Keep Stage 5 conservative: no shared-core source changes were required for RPA beyond consuming existing paths/config/manifest APIs. Begin a separate four-bot architecture review next. Prioritize lifecycle/heartbeat contract implementation, deterministic extension loading, logging initialization and carefully adopted atomic JSON operations, with regression tests for all affected bots. Defer any API/session abstraction until endpoint-specific policies can be injected cleanly without bot-name branches.
