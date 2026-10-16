# TickFlow A-share bar-closure evidence: truthful P0 boundary

**Observation (2026-10-16, live session):** AWS TickFlow Premium research
collector and MCP have 159611.SZ and 518880.SH 5m and 15m bar-end labels
in the current trading day; first due 15m `09:45 Asia/Shanghai` was seen.
Yet every research-cache row deliberately has `is_partial_bar=true` and
`bar_finality=NOT_VERIFIED`. This is a **conservative schema choice**,
not evidence that the bar did not advance. Cache sequence or label crossing
alone cannot assert publisher or exchange finality.

The official TickFlow Kline columnar schema, as currently documented, includes
`timestamp,open,high,low,close,volume,amount`; it does not document a
vendor-attested per-candle `is_final`/close event or revision bound for
`klines.get(...,as_dataframe=False)`. The documented WebSocket `quotes`
channel sends quote snapshots, not a confirmed Kline close event.

Official vendor references:
- https://docs.tickflow.org/zh-hans/api-reference/k线数据/查询-k线数据
- https://docs.tickflow.org/zh-Hans/api-reference/websocket
- https://github.com/tickflow-org/tickflow/blob/main/tickflow/resources/klines.py

## Research-only deterministic stability witness

`data_provider/tickflow_bar_close_witness.py` takes two **already collected
private AWS snapshots**, requests no provider data and emits only fixed
status/counter codes. All checks are required:

1. Genuine TickFlow Premium research envelope and stable exact collector SHA.
2. Different monotonic poll sequences, at least 15 seconds apart; bounded
   timestamps, no stale/future latest poll.
3. Requested current-day bar-end timestamp belongs to 5m/15m/60m grid, and
   **the next grid bar** has appeared *after* its end + >=90s grace.
4. Exact unchanged OHLC, volume, amount and same metadata in both original
   observations, with no missing or malformed rows.
5. All source, Radar, Paper and trading admission remain BLOCKED.

Even success is **STABLE_AFTER_NEXT_LABEL_RESEARCH_ONLY** with
`provider_bar_finality=NOT_VERIFIED`,
`exchange_bar_finality=NOT_VERIFIED`,
`trading_session_calendar=NOT_VERIFIED` and `live_trade=false`.
It can identify prior-bar *revisions* or gaps but **cannot cure** an absent
vendor close acknowledgment. No automatic transition is permitted.

## Prerequisites to truly certify closed bars and admit data

1. Obtain **written TickFlow provider contract** specifying whether any API
   has an authoritative finalized candle flag, timestamp semantics, official
   late-revision policy and permitted feed entitlement, especially for
   1m/5m/15m/60m and ETF quote/lattice shape.
2. If present, implement a source adapter that validates exact provider type,
   schema/version, entitlement, provenance, bar label, observed timestamp,
   and finalized flag; never infer a flag from clock or stable OHLC.
3. If no such field exists, separately validate source tick/quote sequence,
   provider timestamp progression, independently clock-aligned aggregation
   and later revision/reconciliation. Name any result
   `LOCALLY_DERIVED_CLOSED`, **not** `EXCHANGE_FINAL`.
4. Independently accept today's two pilot symbols in AWS with actual code
   and cache runtime/main SHA match, 1m/5m/15m/60m/D1 coverage, timestamp
   closure, no missing labels, independent consecutive polls/reconnect,
   market calendar and observed latency budgets.
5. Only following reviewed merge, controlled deployment, independent SSM
   and MCP readback, and Source Arbiter separate authorization could
   any Radar gate be reconsidered. This PR changes **no** live flags,
   scheduling, paid calls, provider credentials, cloud service or trades.

**IMPORTANT:** Do not simply change `is_partial_bar` from true to false in
`cn_tickflow_research_cache.py`. Its reader explicitly validates that
unverified bars remain research-only; removing that guard would falsely
elevate cached K-lines to trading-grade evidence.
