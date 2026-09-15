# Heartbeat protocol

Stage 8 uses schema version **1**, encoded as strict UTF-8 JSON in a local Unix datagram of at
most 2,048 bytes. Fields are exactly `schema_version`, canonical `bot_id`, UUID
`process_instance_id`, increasing `sequence`, timezone-aware UTC `emitted_at`,
`discord_connected`, `discord_ready`, and `maintenance`. Extra fields, invalid combinations,
unknown bots, unsupported versions, replayed sequences, and non-current instance IDs are rejected.

The supervisor supplies `MDBO_HEARTBEAT_SOCKET` and a random `MDBO_PROCESS_INSTANCE_ID`; neither
is a Discord credential. The socket is mode 0600. The four clients use the shared optional
reporter at a platform cadence of 10 seconds. Sending occurs in a worker thread, has a 250ms
socket bound, coalesces outage logging, and retries on the next cadence. It never raises into or
blocks the Discord event loop. `on_connect`, `on_ready`, and `on_disconnect` update distinct real
Discord signals; reconnects reuse one reporter task and never start business jobs.

Freshness is 30 seconds and startup health timeout is 60 seconds by default. Local ages use a
monotonic clock; wire/event timestamps use aware UTC. These values live in `HealthTiming`, not bot
business configuration.
