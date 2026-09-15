# Stage 9 management authentication

Stage 9 uses an explicit `Authorization: Bearer` management credential on every management
request. `StaticTokenAuthenticator` compares credentials in constant time and maps them to a
server-configured principal. It is deliberately an adapter: a later identity provider can replace
it without changing `SupervisorService` or any bot. The credential is unrelated to, and must never
be sourced from, the four Discord `*_TOKEN` variables.

There is no default credential. Deployment composition must obtain a high-entropy credential from
an external secret facility (for example a systemd credential or root-readable environment file)
and construct `ManagementDependencies`; absent dependencies install no management routes at all.
Credentials must not be put in URLs, manifests, logs, audit records, or committed configuration.

Bearer authentication does not use cookies and browsers cannot attach the header cross-site without
client code possessing the credential. Consequently synchronizer CSRF tokens are not applicable in
Stage 9. CORS is not enabled. If Stage 10 introduces cookie sessions, login, logout, expiry, rotation,
and CSRF protections must be implemented and tested as one change rather than reusing this bearer
credential as a cookie.

Failed authentication attempts are subject to a small per-peer in-process sliding-window limit.
This is intentional local abuse resistance, not a distributed identity/rate-limit service.

Stage 10's browser authentication extension is documented in [stage-10.md](stage-10.md). It uses
local password identities and rotated server-side sessions; it does not place this bearer credential
in a browser cookie or reuse Discord credentials.
