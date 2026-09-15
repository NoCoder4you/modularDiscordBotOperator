# Stage 12 typed bot operations

## Boundary and capability model

Stage 12 extends, rather than replaces, the accepted boundaries. Browser mutations pass through
the Stage 10/11 session and synchronizer-token CSRF checks, `ManagementApplication`, the Stage 9
`DenyByDefaultAuthorizer`, and then `BotOperationService`. `SupervisorService` remains the process
lifecycle and verified-instance authority. `HealthStore` remains the only canonical state
reconciler. The portal does not import any bot package.

Capabilities describe what a registered bot implementation supports; permissions describe what a
principal may do. Both checks are required. Stable capabilities are `cogs.view`, `cogs.load`,
`cogs.unload`, `cogs.reload`, `cogs.reload_all`, `commands.sync`, `maintenance.view`,
`maintenance.enable`, and `maintenance.disable`. Stable Stage 12 permissions are `cogs.view`,
`cogs.manage`, `commands.sync`, `maintenance.view`, and `maintenance.manage`. As with earlier
permissions, the authorizer also applies the principal's server-owned bot assignment.

The immutable `TRUSTED_CAPABILITY_CATALOG` maps the four canonical bot IDs to capabilities and
safe cog IDs. Client data can neither add a capability nor supply an extension name. A cog ID must
be a short lowercase kebab identifier and must resolve in that bot's catalog before the adapter is
called.

## Audited capability matrix

The migrated implementations all load setup-bearing extensions at startup and contain a configured
global `bot.tree.sync()` path. None currently implements an application-enforced, persistent generic
maintenance contract. Stage 12 therefore exposes typed maintenance methods but advertises no
maintenance capability; requests fail closed rather than creating a portal-only flag.

| Bot | Cog view | Load | Unload | Reload | Reload all | Command sync | Maintenance |
|---|---:|---:|---:|---:|---:|---:|---:|
| `cda-admin` | yes | yes | yes | yes | yes | global | no |
| `cda-pay` | yes | yes | yes | yes | yes | global | no |
| `unbot` | yes | yes | yes | yes | yes | global | no |
| `rpa-admin` | yes | yes | yes | yes | yes | global | no |

Cog IDs are deterministic kebab-case names derived during the source audit, not at request time.
They include the setup-bearing cogs in each package. `cda-admin`'s `admin-manager` and
`cogs-loader` are conservatively marked required: they cannot be loaded, unloaded, reloaded, or
included in reload-all. The other audited cogs are startup-loaded and may be loaded after a typed
unload. Reload-all sequentially reloads only trusted reloadable entries; it continues after adapter
extension failures and reports deterministic succeeded/failed counts. An instance change aborts
the operation rather than being treated as a partial extension failure.

## Control transport and prerequisites

`BotControlAdapter` is the narrow bot-side contract. It has explicit list/load/unload/reload,
configured command-sync, and typed maintenance methods; it has no generic action method. A
production implementation must use an authenticated, filesystem-permission-protected local channel
bound to the current process instance. It must not reuse a Discord token. The heartbeat socket
remains telemetry-only and is never used to queue commands. Stage 12 includes a deterministic fake
adapter; production transport deployment remains fail-closed until an adapter is explicitly
injected.

Cog and maintenance operations require Stage 7 `RUNNING`, verified process identity, a matching
Stage 8 process instance, and an available management channel. Command sync additionally requires
a fresh Stage 8 heartbeat and Discord READY. The portal never creates a Discord client, handles a
token, accepts a guild ID, or submits command payloads. Sync always uses the bot's audited global
scope.

The service captures `bot_id`, `process_instance_id`, and `operation_id` before transport work and
checks the instance again after every mutation. The Stage 7 per-bot lock is shared where
`SupervisorService` supplies it, so restart versus reload/sync conflicts fail with
`operation_in_progress`; separate bots remain independent. Stopped, transitional, unverified,
stale, and not-READY states map to bounded errors such as `bot_not_running`,
`lifecycle_operation_in_progress`, `bot_not_ready`, and `process_instance_changed`.

## Operations, UI, and security

Application records are distinct from lifecycle records and contain an operation UUID, request ID,
canonical bot ID, bound instance ID (never rendered), typed operation, timestamps, status, safe
summary, and bounded error code. History defaults to 20 and is hard-capped at 100, reverse
chronological, bot-authorized, and IDOR-safe. The bot detail page conditionally renders Overview,
Lifecycle, Cogs, Commands, Maintenance, and Operations sections only when capability, permission,
and current validity permit them. All mutations are POST-only and retain form CSRF validation,
same-origin behavior, 4096-byte limits, and the existing per-principal/per-bot mutation limiter.

Audit events correlate actor, bot, safe cog ID, request ID, operation ID, result, and timestamp.
Adapter exception text and internal extensions are never copied to records, HTTP errors, HTML, or
audits. Application-operation lookups return not-found for missing or unauthorized records.

Stage 12 exposes **no** arbitrary shell, PTY, stdin, process/PID/argv/systemd-unit operation,
filesystem browser, arbitrary import/module/Python method, raw Discord API, `eval`, `exec`, upload,
JSON editor, or configuration editor. Internal extension strings are sent only by the trusted
service to the trusted adapter. No production process, host configuration, Discord command set, or
maintenance state is touched by the test suite.

## Deferred work

The accepted ADRs leave production systemd/polkit and application-control transport deployment
deferred. Consequently, bootstrapping must inject an instance-authenticated adapter explicitly;
absence produces `management_channel_unavailable`. A future bot-side maintenance contract may add
capabilities only after it enforces commands and reports evidence in heartbeat; Stage 8 will then
derive `Maintenance`. Maintenance is never stored in a browser session or parallel portal state.
