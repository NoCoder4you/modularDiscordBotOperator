# CDA Admin inventory

## Inventory status

The Stage 2 inventory is **blocked** because the source repository
`NoCoder4you/CDA-Admin` is not present in this workspace and could not be read from
GitHub from the build environment. The attempted source checkout failed before any
files were obtained:

```text
git clone https://github.com/NoCoder4you/CDA-Admin.git
fatal: unable to access ... CONNECT tunnel failed, response 403
```

No inventory of commands, cogs, identifiers, data schemas, dependencies, or runtime
behaviour is asserted here. Doing so without the reference implementation would risk
inventing behaviour and would violate the migration's preservation requirement.

## Required source input

Before Stage 2 implementation resumes, make a read-only checkout or archive of the
complete CDA Admin repository available alongside this repository. It must include
the Git revision being migrated and all tracked files, including history if secret
history auditing is required. The reference checkout must not be modified.

Once available, inventory at least:

- the entry point and every cog/module;
- command names, signatures, checks, cooldowns, messages, and embeds;
- intents, listeners, tasks, views, modals, and extension loading;
- every JSON/status file and all read/write paths and schemas;
- every Discord snowflake, classified as deployment configuration or application
  constant (snowflakes are not secrets);
- environment variables and any suspected credentials (without reproducing values);
- startup, reconnect, error, and shutdown behaviour;
- imports, external APIs, and exact third-party dependency constraints; and
- existing tests, stating whether each is retained, adapted, replaced, or dropped.

The resulting inventory must record the exact source commit SHA so later behaviour
comparisons are reproducible.

## Repository history checked

The current monorepo history contains a previously deleted generic `discord-bot/`
foundation. It describes itself as a Stage 1 foundation and is not treated as CDA
Admin source. Reusing it would not constitute a migration from CDA Admin.
