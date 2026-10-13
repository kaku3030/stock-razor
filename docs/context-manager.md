# Context Manager MVP

Context Manager keeps a small durable current state and an append-only event
log so a new chat can recover engineering context through the existing
read-only MCP service. It is not conversation history, a scheduler, a secret
store, or a trading control plane.

## Storage contract

- `STOCK_RAZOR_CONTEXT_STATE_PATH` points to the compact current JSON file.
- `STOCK_RAZOR_CONTEXT_EVENTS_PATH` points to the append-only JSONL log.
- Every event has a schema version, monotonic version, event ID, timestamps,
  source, source reference, TTL, and sanitized payload.
- Repeating an event ID with the same payload is idempotent. Reusing it with a
  different payload is rejected.
- Expired, failed, corrupt, or version-mismatched state is returned as
  `BLOCKED` or `EXPIRED`; it is never promoted to a pass.
- The safety fields always remain `radar_admission=BLOCKED`,
  `source_arbiter_admission=BLOCKED`, `paper_auto_ready=false`, and
  `live_trade=false`.

## Producers and recovery

Radar publishes automatically record a `radar_published` event when the state
path is configured. The read-only MCP surface exposes
`get_context_manager_state`. Deployment installation records a sanitized
`deployment_passed` event after the service is active. CI and other engineering
producers can use `python scripts/record_context_event.py` with the same
environment variables; it prints only the event result, never the payload.

This MVP intentionally does not create reminders or automations, and it does
not claim that deployment or a successful MCP read proves provider access,
Radar qualification, paper readiness, or trading readiness.
