# Canonical state reconciliation

`supervisor.health.reconcile` is the only health-state authority. It is pure and performs no
process action. The portal must consume snapshots rather than recreate this logic.

| Precedence | Evidence | State |
|---:|---|---|
| 1 | manifest disabled | Disabled |
| 2 | crash-loop latch | Crash Loop |
| 3 | trusted restart active | Restarting |
| 4 | maintenance acknowledged by current instance | Maintenance |
| 5 | verified unexpected exit, process absent | Crashed |
| 6 | desired stopped, process absent | Offline |
| 7 | conflict/unverified identity or missing process evidence | Unknown |
| 8 | verified process within 60s grace, health incomplete | Starting |
| 9 | verified process, fresh heartbeat, Discord disconnected or not READY | Disconnected |
| 10 | verified process, fresh heartbeat, connected and READY | Online |

After grace a missing/stale heartbeat becomes `Unknown`; a later valid heartbeat recovers. A
disconnect becomes `Disconnected`, and reconnect plus READY becomes `Online`. Expected shutdown
becomes `Offline`; an unexpected exit becomes `Crashed`; a trusted restart moves it to
`Restarting`/`Starting`. Conflicts always resolve conservatively and never initiate destructive
action. Meaningful snapshot/reason changes emit credential-free `bot.state.changed` events;
healthy heartbeat traffic is silent.
