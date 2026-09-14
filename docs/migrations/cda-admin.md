# CDA Admin migration

## Status: blocked before implementation

Stage 2 has not been implemented. The authoritative source repository
`NoCoder4you/CDA-Admin` was unavailable in the workspace and network access to it was
denied. See [the inventory record](cda-admin-inventory.md).

The existing `bots/cda-admin/bot.toml` is a Stage 1 placeholder; it is not evidence
that CDA Admin has been migrated or is runnable. No source files, production data,
or guessed dependencies have been copied, and no CDA Admin behaviour has been
invented.

## Why implementation must wait

The requested work is explicitly a behaviour-preserving migration. Without the
source it is impossible to determine safely:

- commands, permissions, messages, embeds, timing, and audit rules;
- data filenames and JSON schemas;
- required intents, IDs, environment variables, and dependencies;
- extension discovery, lifecycle, and background-task behaviour; or
- suitable offline characterization tests.

Scaffolding a replacement bot would therefore be a redesign rather than a
migration. CDA Pay and shared business abstractions remain intentionally untouched.

## Resume criteria

Provide a readable, immutable checkout/archive of `NoCoder4you/CDA-Admin`, including
the intended source commit. Then perform the inventory before changing application
code. After inventory, the migration should add the self-contained package under
`bots/cda-admin/`, validate its manifest through Stage 1, isolate data under
`runtime/data/cda-admin/`, document production cutover and rollback, and add offline
characterization tests derived from the observed implementation.

No production-data move should occur as part of source migration. The eventual
deployment plan must stop and back up the old process, copy and validate its JSON in
the isolated runtime root, verify ownership, start only the new CDA Admin process,
verify Discord READY and expected features, and retain the rollback copy until the
old process can safely be retired.
