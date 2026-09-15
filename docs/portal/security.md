# Stage 9 security and deployment boundary

The accepted ADR 0004 design is implemented as a typed authenticated client layer over the existing
supervisor. The intended topology is browser/future portal over HTTPS to a same-origin portal,
followed by this management application layer and the in-process `SupervisorService`/`HealthStore`.
When served directly, Uvicorn must bind only to `127.0.0.1` (for example
`uvicorn portal.app:app --host 127.0.0.1`) or an equivalently permissioned Unix socket. It must never
bind publicly by default. A production reverse proxy terminates TLS on the trusted host; Stage 9 does
not install or modify that proxy, systemd, users, sudoers, polkit, or processes.

The portal and supervisor should run as a dedicated least-privilege Unix identity. The management
credential comes from external secret storage and is supplied only to portal composition. Discord
credentials remain supervisor-to-bot launch secrets and are not authentication material. Forwarded
`X-User`, `X-Role`, and `X-Admin` values are ignored. No CORS middleware is installed.

Responses receive a generated correlation ID plus `nosniff`, no-referrer, deny-framing, and a
deny-all baseline CSP. Audit events include time, request ID, principal ID, permission/action,
canonical bot ID, operation ID, and bounded result—but never request authorization or body data.
Lifecycle mutations are locally rate-limited per principal and bot. Errors are safe-mapped; logs use
only request IDs and bounded error categories because exception messages can contain sensitive
process details.

## Test fixture isolation

Three UNBOT pure-helper tests previously installed fake `discord` and `aiohttp` packages directly in
global `sys.modules` and left them there after collection. Later RPA Admin collection therefore saw a
hybrid fake/real Discord package. Each loader now snapshots every replaced module and restores or
removes it immediately after executing its isolated source module. The loaded helper retains its
references while unrelated suites see their original import state, making collection order neutral.
