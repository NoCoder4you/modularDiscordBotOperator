# Supervisor architecture (Stage 7)

## Scope and ownership

The supervisor is an asynchronous Python service contract for catalog discovery and typed
`start`, `stop`, and `restart` operations. It does not import bot packages, instantiate Discord
clients, expose HTTP, accept arbitrary commands, manage application health, or edit bot data.

ADR 0002 remains authoritative: **systemd owns production processes and the supervisor owns
policy**. Stage 7 implements the shell-free subprocess adapter expressly permitted for development
and deterministic integration tests, while keeping the lifecycle service separate from that
adapter. Production D-Bus/polkit and unit installation remain deployment work; no competing
production process manager or host unit was created.

The registry loads `bots/*/bot.toml` only below a caller-supplied, resolved repository root. It
validates canonical IDs and manifest fields, rejects duplicate IDs, and resolves executable,
working, and runtime paths under trusted roots. The current catalog contains exactly `cda-admin`,
`cda-pay`, `unbot`, and `rpa-admin`. Each manifest selects a repository-relative per-bot virtual
environment and a bounded shutdown timeout. Missing environments fail at start rather than falling
back to `PATH`.

Each bot now has minimal `src`-layout package metadata, so deployment can install its package and
requirements into the manifest-selected virtual environment. This closes the Stage 6 clean-launch
blocker without merging dependencies or changing bot imports/business behavior.

## Service lifecycle and boundaries

`SupervisorService.startup()` validates durable evidence and begins accepting operations.
`shutdown()` stops accepting work, atomically persists minimal metadata, and cancels capture/wait
tasks. It deliberately does **not** terminate managed processes. This supports systemd ownership and
the principle that restarting the control plane must not restart healthy bots.

The platform passes only a small allow-list of benign base environment keys, the bot's one derived
token variable, its isolated runtime root, and a generated process instance ID. Token values never
enter argv, registry/process/operation records, state files, event metadata, or model repr output.
Runtime directories are `runtime-root/<validated-id>` and are created mode `0700`; the supervisor
does not inspect or mutate their contents.

The subprocess adapter uses `asyncio.create_subprocess_exec` with an argument vector, explicit CWD,
closed stdin, a new process session, and bounded stdout/stderr line storage (1,000 records by
default, 16 KiB per line). Records identify bot, instance, stream, sequence, and receipt time.
This is capture plumbing only—not a console or streaming API.

## Audit boundary and deferred work

Operations emit structured requested/succeeded/failed events and exits emit
`bot.process.exited`. An optional opaque actor string is carried without portal coupling. There is
no persistent user-facing audit store yet. Stage 8 should add heartbeat and Discord READY evidence,
reconciliation, and systemd invocation/cgroup correlation; it must not reinterpret process
`running` as Discord `online`.
