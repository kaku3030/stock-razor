# TickFlow Expert ¥199/month — A-share throughput planning (2026-10-12)

## Confirmed operator-supplied plan screenshot (2026-10-11)

This is a **monthly subscription**, not a reason to treat every REST call
as a separate large payment. Prior operational testing was therefore overly
conservative. The plan details recorded from the operator's image are:

| Feature | Screenshot limit |
| --- | --- |
| Realtime REST quotes | 300 requests/minute, up to 500 symbols/request |
| Daily batch K-line | 120 requests/minute, up to 200 symbols/request |
| Minute batch K-line | 60 requests/minute, up to 200 symbols/request |
| Single-symbol minute K-line | 120 requests/minute |
| Historical minute entitlement | Up to 365 days |
| Max bars/rows per response | 10,000 |
| Minute periods | 1m / 5m / 15m / 30m / 60m |
| WebSocket quote symbols | Up to 200 symbols per connection/session limit as advertised |
| Other APIs | L2 five-level, financial data, ex-rights indicated |

**Verification boundary:** these are *plan screenshot* values, not audited
provider/account entitlements. Unknowns include per-account sharing across
AWS+Windows, connection counts, per-minute chargeability/overage, SDK return
shape, and provider-side 429 behavior. Monthly billing does not guarantee
unlimited high-frequency API usage.

## Planning change and actionable throughput

New offline `data_provider/tickflow_expert_capacity_plan.py` models
the screenshot rather than forcing every research task into a 1-call pilot.
It produces **counts only**, with no network or actual quota reservation.

At 25% reserved headroom (to reduce collisions with Windows and AWS),
the provisional global targets are: 225 quote requests/min,
90 daily-batch requests/min, 45 minute-batch requests/min and
90 single-symbol-minute requests/min. These are NOT simultaneously
authorized quotas: multiple operations may share one provider account.

Planning examples:

- 5,000 ETFs batched 500 at a time for quote snapshots: 10 requests
  instead of 5,000, within one theoretical minute.
- 5,000 ETFs at 15m with 16 same-day bars each: 25 minute-batch calls.
- 5,000 ETFs at 1m with 240 bars each: row limit matters.
  200*240=48,000 exceeds 10,000 rows/request, therefore batch at
  41 symbols and 122 calls; theoretical `ceil(122/45)=3` minutes.
- 5,000 WebSocket symbols imply at least 25 200-symbol sockets; because
  allowed **socket count and shared account rights are not verified**,
  planner marks this UNKNOWN, not deployment approval.

The 5-symbol/1-call legacy pilot in
`data_provider/tickflow_cloud_history_plan.py` intentionally remains a
strict separate pilot. The new capacity plan addresses future scaling
without weakening its existing billing guard.

## Implementation backlog

1. Use confirmed package capability efficiently: 15m and 60m complete
   day history, explicit exchange timestamps and independent OHLCV parity
   first. Existing 2026-10-12 AWS premium run #38202661351 already
   returned SDK, quote, all requested 1/5/15/30/60m REST, five-level depth
   `COMPLETED` at latest code without WebSocket; this is *interface
   capability*, not provider timestamp currentness or complete bars.
2. Prove TickFlow row limits, source identity, session semantics and
   provider callback continuity during the *actual* afternoon market,
   not the 11:30–13:00 China lunch break.
3. Implement **real shared cross-host rate coordination** (one quote
   connection + coalesced requests + 429 backoff/jitter), including API
   failures, reconnect storm protections and a small global max to keep
   AWS and Windows from fighting for account capacity. Pure plan is NOT
   a rate limiter.
4. Use bounded cached fanout: subscribe to valid candidate symbols once
   when eligible, persist arrival and provider timestamps independently,
   serve multiple consumers from snapshots; plan full-market coverage
   with transparent capability and cost gates.
5. Source Arbiter promotion requires independent PIT/session calendar,
   full-day 15m/60m closure, data parity, OOS/Shadow and alert/kill switches.
   Stop misleadingly equating healthy heartbeat, 2 quote rows or API
   `COMPLETED` with live qualified market data.

No AWS/paid requests, broker calls, real/sim orders, quota reservations,
source promotions or permission modifications occur by merging this
planner.

`PAPER_AUTO_READY=NO`, `RADAR_ADMISSION=BLOCKED`,
`SOURCE_ARBITER_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`.
