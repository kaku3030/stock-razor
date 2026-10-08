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
