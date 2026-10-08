# AWS Cloud Fast-Path Read Benchmark V0.1

Status: **read-only diagnostic evidence**, never data qualification or Radar
admission.

The manually dispatched GitHub Actions workflow
`benchmark-cloud-fast-path-readonly.yml` runs existing
`scripts/benchmark_cloud_fast_path_reads.py` on the already deployed AWS
read-only MCP checkout, through bounded AWS Systems Manager commands using
temporary GitHub OIDC credentials.

- US: AMD, NVDA, TSLA and QQQ, 30 local read iterations.
- CN: 159611 and 518880, 15-minute frame, 30 local read iterations.
- Emits only filtered `P50/P95/P99`, observed/missing counts and exact
  deployed MCP repo SHA; it never prints bars, prices, holdings, provider raw
  errors, API keys or environment values.
- Reads current livefeed, canonical, Radar and CN observer JSON through
  current immutable runtime readers; no network market-data requests, live
  subscriptions, service restarts, broker access or trading actions are
  initiated by this benchmark.
- `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`.

**Critical:** Thirty repeated cache reads measure read-surface latency only.
They are not 30 independent provider network requests or Radar compute
events. Their provider/callback/worker latencies may be duplicates of a
single source sequence. Report status remains
`REPEATED_READ_DIAGNOSTICS_ONLY`, and provider→MCP→ChatGPT full E2E plus
sustained SLO remain `NOT_VERIFIED`.

Next qualification requires uniquely timestamped provider/worker events,
full session/timeframe completeness and provider lineage, quality checks,
P50/P95/P99 under load across market hours, actual MCP transport latency,
and evidence while the user's desktop is offline.

## Per-symbol CN coverage (V0.2 diagnostic slice)

Alongside cache-read percentiles the benchmark now emits a bounded, single-read
`cn_symbol_read_diagnostics` record for each requested Chinese market symbol.
Only whitelisted fields are published: read status, provider/fallback source,
timestamp semantic, currentness flags, source age, and row count.
**No price/OHLCV rows, raw error messages, credentials, or proprietary
holdings are logged.**

A provider source may pass timestamp/currentness checks for a completed
session but still lack bar continuity, completeness, next-session freshness,
cross-source correctness and Radar approval. Consequently the report always
states `data_qualification=NOT_VERIFIED` and
`radar_admission=BLOCKED`. The added `read_success_rate` is only
the read-surface status rate, not a market data quality acceptance score.

## US OpenD health and bar-coverage diagnostics

The US fast-read benchmark now also emits one bounded `us_cloud_read_diagnostics`
view per run. It separates health, market session, delivery mode, bar-closure
evidence, canonical snapshot state, Radar read/poll status, and the number of
cached 1m/5m/15m/1h bars for each requested US symbol.

This is needed because **fast cached reads with `read_success_rate=0`**
do not prove that the market stream is available. During a closed market,
absent bars, stale snapshots and blocked Radar are plausible and must
be reported separately; the diagnostic must not invent a failure cause.

Only whitelisted statuses and counts are emitted; no price bars, last trade
values, raw errors, account data or credentials enter GitHub logs.

`data_qualification=NOT_VERIFIED`,
`radar_admission=BLOCKED`, and `can_confirm_signal=false` continue to
apply even if all component statuses are HEALTHY. A US market-session
qualification with advancing 1m/5m/15m/1h source data is a separate step.

### US symbol namespace

The canonical US market reader returns cache keys with `US.` prefixes
(e.g. `US.AMD`), even when the benchmark requests bare tickers
(`AMD`). Coverage lookups MUST normalize requested tickers to this
namespace before counting presence. An unnormalized lookup previously
misreported present source symbols as absent; this error does not itself
establish a provider failure or missing bar. Remaining source staleness,
bar-closure and Radar admission checks remain independent.
