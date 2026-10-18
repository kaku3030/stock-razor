# OpenD native US K-line / TickFlow performance comparison (read-only)

## Purpose

Benchmark equivalent scopes separately rather than equating provider network calls
with cloud JSON cache reads or the ChatGPT MCP round-trip.

- **Native provider**: on EC2, one quote context, `get_cur_kline` for
  pre-subscribed US.AMD / US.QQQ and preexisting 1m / 5m / 15m / 60m periods,
  counts 1, 100, 500, 1000, 1001, 2000, maximum 65 total calls.
- **Quota and safety**: `query_subscription(is_all_conn=False)`; skip any
  symbol-period combination without a subscription owned by this connection.
  The standalone script opens a fresh connection, which normally has none;
  it then reports `BLOCKED_NO_PREEXISTING_KLINE_SUBSCRIPTION` with zero K-line
  calls. A different connection's subscriptions do not qualify this caller.
  This block does not establish whether provider entitlement is valid. Do **not** call
  subscribe, unsubscribe, historical K-line quota API, any trade API, OpenD
  restart, secrets API or production data writer. A rejected size is not
  retried indefinitely. No raw quotes, prices or credentials in Actions logs.
- **Validation**: retain requested and actual row counts, timestamp order,
  duplicates, finite OHLCV, request timing, error category (not error text).
  Observe provider cap vs truncation without assuming requested==returned.
- **Warm repeats**: 12 requests of 100 rows on the first available
  pre-subscribed series; p50/p95 refer to **actual OpenD native query calls**.
- **Cached US and CN benchmark**: use existing
  `benchmark-cloud-fast-path-readonly.yml` 30 iterations; that measures
  cached canonical and Radar **reads**, not model inference, provider callback
  or actual Radar computation. A cached heartbeat is NOT a separate newly
  sampled provider latency.
- **ChatGPT interface**: manually time already-connected
  `get_market_snapshots`, `get_market_analysis`,
  `get_cn_market_data(symbol="TICKFLOW:FAST")` requests in the same
  conversation. These timings include tool transport and are **not native
  OpenD/SDK timing**.
- **Response-generation duration**: current tool interfaces do not provide
  a reliable user-message-to-complete-answer tracing clock or token-render
  telemetry. Report that slice as `NOT_MEASURED`, not 0ms.

Provider references: [subscription scope](https://openapi.futunn.com/futu-api-doc/en/quote/query-subscription.html)
and [native K-line subscription prerequisite and 1000-bar limit](https://openapi.futunn.com/futu-api-doc/en/quote/get-kl.html).

## Acceptance boundary

Native post-close success proves the requested historical retrieval interface,
not realtime US market freshness, bar close finality, subscription continuity,
reconnect behavior, risk admission or a long-running load SLO. Today's US
session may not have begun; document `STale`/unproven rather than invent live.
All trading and Radar gates stay blocked.

Workflow: `.github/workflows/benchmark-opend-native-klines-readonly.yml`
Script: `scripts/benchmark_opend_native_klines_readonly.py`

For an authorized native retrieval test, reuse the existing quota-guarded
`benchmark-opend-owned-connection-readonly.yml` (1m) and
`benchmark-opend-owned-multitimeframe.yml` (5m/15m/60m/D1) workflows. These
establish and verify bounded subscriptions on their own temporary connection,
close it on exit, and leave production subscriptions unchanged. Their native
retrieval results still do not establish live freshness or bar finality.
