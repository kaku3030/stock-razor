# OpenD native US K-line / TickFlow performance comparison (read-only)

## Purpose

Benchmark equivalent scopes separately rather than equating provider network calls
with cloud JSON cache reads or the ChatGPT MCP round-trip.

- **Native provider**: on EC2, one existing quote context, `get_cur_kline` for
  pre-subscribed US.AMD / US.QQQ and preexisting 1m / 5m / 15m / 60m periods,
  counts 1, 100, 500, 1000, 1001, 2000, maximum 65 total calls.
- **Quota and safety**: `query_subscription(is_all_conn=True)`; skip any
  symbol-period combination without an existing subscription. Do **not** call
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

## Acceptance boundary

Native post-close success proves the requested historical retrieval interface,
not realtime US market freshness, bar close finality, subscription continuity,
reconnect behavior, risk admission or a long-running load SLO. Today's US
session may not have begun; document `STale`/unproven rather than invent live.
All trading and Radar gates stay blocked.

Workflow: `.github/workflows/benchmark-opend-native-klines-readonly.yml`
Script: `scripts/benchmark_opend_native_klines_readonly.py`
