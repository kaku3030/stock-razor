# US OpenD 30-minute read-only audit

This workflow is intentionally disabled until the repository variable
`US_OPEND_30M_AUDIT_ENABLED` is explicitly set to `true`. It is a research
audit, not a production scheduler, deployment mechanism, trading path, or
Radar admission gate.

The scheduled trigger runs every 30 minutes on weekdays in UTC. The job then
uses `exchange-calendars` `XNYS` with `America/New_York` timestamps to decide
whether the current slot is 09:30, 10:00, ... through the actual session
close. This handles DST, weekends, NYSE holidays, and early closes. A missing
or failing calendar blocks the run; it does not fall back to weekday logic.

Before any cloud read, the job requires the persistent `FEEDBACK_HUB_PATH`,
reads the Feedback Hub, deduplicates the ET slot, and claims the item. A
missing or corrupt Hub blocks the run. The cloud probe only reads the existing
US LiveFeed and Radar exports over the existing bounded SSM path. It does not
create provider contexts, change subscriptions, restart services, deploy,
send paid model requests, read or mutate positions, or place orders.

The report preserves `UNKNOWN`/`NOT_VERIFIED` for layers not emitted by the
existing runtime, including 5m, D1, provider-wire latency, disconnect recovery,
and holdings. `RADAR_ADMISSION`, `SOURCE_ARBITER_ADMISSION`, `PAPER_AUTO_READY`,
`LIVE_TRADE`, and `TRADE_EXECUTION` remain closed.

## Explicit activation requirements

1. Merge the Feedback Hub prerequisite and this PR after exact-head CI passes.
2. Provision and independently verify a durable cloud-backed `FEEDBACK_HUB_PATH`.
3. Set `US_OPEND_30M_AUDIT_ENABLED=true` only after reviewing the target and
   notification policy.
4. Confirm a bounded read-only cloud run and its sanitized artifact. No step
   in this PR authorizes deployment, production scheduling, or trading.
