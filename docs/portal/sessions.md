# Portal sessions (Stage 11)

`SessionStore` remains replaceable. `MemorySessionStore` is bounded and deterministic for development
and unit tests. `SQLiteSessionStore` is the recommended single-host production adapter and shares the
migrated identity database so administrative identity updates and persistent-session deletion commit
atomically.

The browser receives a random 256-bit opaque token. SQLite stores only its standard SHA-256 digest,
plus the identity ID, CSRF synchronizer token, creation/last-seen/absolute-expiry times, and the
identity `session_revision`; it stores no password verifier or bot/platform credential. Lookup hashes
the presented token, enforces the 30-minute idle and eight-hour absolute defaults, and touches the
last-seen time. Creation cleans expired rows and evicts the least-recently-seen row at the configured
bound (1,024 by default). No scheduler is required.

Persistent sessions survive an ordinary portal restart. They do not survive password, enabled,
permission, administrator, or bot-restriction changes: the update increments the identity revision
and deletes all matching persistent rows in the same SQLite transaction. The browser transport also
compares a session's issued revision against the freshly loaded identity on every protected request,
so an old memory session is rejected and its CSRF token cannot authorize a mutation. Rotation at
login invalidates the anonymous token before issuing an authenticated token; logout deletes it.
