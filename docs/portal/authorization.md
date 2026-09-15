# Stage 9 management authorization

Authentication and authorization are separate adapters. `DenyByDefaultAuthorizer` recognizes only
`bots.view`, `bots.start`, `bots.stop`, `bots.restart`, and `operations.view`; a permission must both
be recognized and explicitly assigned. Client headers, claimed roles, and UI visibility are never
authorization evidence.

Every decision accepts a canonical `bot_id`. A principal may carry an optional server-owned bot-ID
allow-list, making calls such as `can(actor, "bots.restart", bot_id="cda-admin")` ready for later
RBAC policy. Catalog listing filters inaccessible bots. Mutation authorization happens before the
corresponding supervisor method is invoked, and operation access is checked against the operation's
server-owned bot ID.

Stage 9 intentionally has no user-management UI, role editor, forwarded-identity trust, or Discord
OAuth. Static principal configuration is deployment-owned and must remain outside client control.
