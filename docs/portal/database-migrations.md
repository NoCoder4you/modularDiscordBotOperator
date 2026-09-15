# Portal database migrations (Stage 11)

The identity SQLite file is owned by the portal Unix account and has an authoritative
`portal_schema_version` singleton. The repository-owned ordered migration tuple is `001_initial`,
`002_identity_security_revision`, and `003_persistent_sessions`. Startup takes SQLite's
`BEGIN IMMEDIATE` write lock, applies each pending migration and its version update in one
transaction, and commits only after all work succeeds. Any error rolls the whole transaction back;
the file is never deleted or recreated. A version newer than the application supports fails closed.
All chosen SQLite DDL (`CREATE TABLE`, `CREATE INDEX`, and `ALTER TABLE ADD COLUMN`) participates in
SQLite transactions; no non-transactional migration operation is used.

Only one portal worker is recommended. SQLite serializes accidental concurrent initializers for 30
seconds; this is not distributed locking. Back up the identity database (including WAL state when
applicable) before upgrades. On failure, stop the portal, retain the error and database, restore a
known-consistent protected backup if necessary, then retry with the same/newer application. Never
delete production identity data as automatic recovery.
