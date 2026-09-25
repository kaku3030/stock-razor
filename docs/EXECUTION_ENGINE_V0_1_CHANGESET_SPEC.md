# EXECUTION_ENGINE_V0.1_CHANGESET_SPEC

Status: implementation candidate, paper/offline only. Base: `origin/main`
at `76526b3c3ca24dacfacf03506b6ac9cc911004ea`.

## Owner and boundary

The unique component owner is `src/services/execution_engine.py` under the
AI Monitor / Runtime Production Owner boundary. This is not a fifth product
line and does not modify PR #148, LiveFeed, Radar, or existing portfolio
read/analysis semantics.

The engine owns validation, fail-closed risk checks, intent identity, order
state transitions, paper adapter calls, and an append-only SQLite journal with
unique broker-order/fill identities. The journal is idempotent and recoverable;
it does not claim exactly-once delivery. An ambiguous submission blocks until
an external reconciliation proves its outcome.
It does not own strategy decisions, market-data collection, real accounts, or
broker credentials. Strategy, QQQ Gate, Entry Gate, SRVP, VWAP, and model
outputs are inputs only; none can call an adapter directly.

## Frozen V0.1 contract

- `OrderIntent` requires intent/account/broker/strategy/evidence lineage and
  rejects free-form broker payloads.
- Startup reconciliation is mandatory. Missing, stale, or incomplete account
  state and stale/unknown market-data time block submission.
- The only enabled adapter capability is a factory-issued `PAPER` capability;
  a protocol-shaped or forged adapter is rejected at construction. No Alpaca,
  Moomoo, OpenD, SDK, socket, HTTP, credential, or trade-unlock path exists in
  this changeset.
- Duplicate `intent_id`, terminal cancel/replace, invalid fills, whitelist,
  session, TTL, kill switch, daily loss, order size/notional, exposure,
  slippage, and outstanding-order limits fail closed.
- Paper order state is `INTENT -> VALIDATED -> SUBMITTING -> ACCEPTED ->
  PARTIAL/FILLED`, with explicit `CANCELLED` and `REJECTED` terminal values.
  The journal retains lineage and broker/fill identifiers.

## Reuse versus new

Reused as documented boundaries only: `src/services/stock_radar_v2/execution_reality.py`
for shadow-execution semantics; `src/services/portfolio_service.py` and
`src/brokers/futu/portfolio.py` as existing portfolio/read-model references;
`src/agent/tools/execution.py` as tool-runner cancellation infrastructure.
None is an execution owner or imported by this slice.

New: the engine, its adversarial offline tests, and this specification.
Explicitly untouched: `data_provider/alpaca_market_data_adapter.py`, PR #148
LiveFeed code, Futu/OpenD code, Radar/strategy code, APIs, schemas, workflows,
credentials, deployment, and production configuration.

## Promotion gates

`PAPER_AUTO_READY` remains blocked pending independent acceptance of the
expanded restart/reconnect and reconciliation evidence, even though the
offline suite passes. `LIVE_SHADOW_READY=NO` until a separate shadow harness
and human comparison evidence exist. `TINY_LIVE_AUTO_READY=NO`: this slice
contains no live switch or live adapter and cannot unlock or mutate a real
broker.
