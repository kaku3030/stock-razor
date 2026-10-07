# Local Data + VTI + Vibe-Inspired Integration V0.1

Status: RESEARCH_ONLY / LIVE_TRADE=NO

## Goal

Add the useful ideas from KLineChart and Vibe-Trading without making either project a source of market-data truth or an execution authority.

## Boundaries

- Canonical market-data ownership stays in STOCK RAZOR backend workers.
- KLineChart is a rendering layer only.
- Vibe-Trading is an architectural reference only; no Vibe code is copied.
- The local settled-bar cache is a downstream performance cache only.
- Cache reads never prove currentness, entitlement, timestamp semantics, closure, provider authority, or trading permission.
- A cache miss may cause the existing approved provider path to fetch data; the cache itself performs no network I/O.
- LIVE_TRADE remains NO.

## V0.1 pieces

### 1. SettledBarCache

Path: data_provider/local_bar_cache.py

- SQLite WAL storage
- zlib-compressed payloads
- idempotent upsert by market/symbol/timeframe/bar_end_utc
- accepts only is_closed=true AND is_complete=true
- bounded chronological reads
- compression/storage accounting
- no provider SDK imports
- no fallback routing
- no canonical promotion

This captures the useful local-cache idea used by modern research systems: historical settled bars are stored once and reused instead of repeatedly calling remote providers.

### 2. KLineChart v10 adapter

Path: apps/dsa-web/src/components/market/

- canonical bar -> KLineChart KLineData
- millisecond timestamps
- 1m/5m/15m/1h/1d period mapping
- dedupe + ascending-order normalization
- read-only React chart component
- no browser-side provider or OpenD access
- no secret-bearing canonical API call from the browser

KLineChart v10 uses setDataLoader; legacy applyNewData/updateData APIs are not used.

### 3. Vibe-Trading ideas adopted as design constraints

We adopt the ideas, not the implementation:

- settled historical data should be cacheable locally
- a cache hit should avoid unnecessary upstream requests
- forming/unsettled bars must not be persisted as settled history
- provider health/fallback must stay explicit
- research/backtest workloads must be isolated from broker/API secrets

Existing STOCK RAZOR provider routing and safety gates remain authoritative.

## Next gates

1. Wire cache behind an explicit cache policy in one research-only historical path.
2. Measure cold read, warm read, compression ratio and 5,000+ symbol batch behavior.
3. Add a server-side VTI bridge that can authenticate the browser without exposing STOCK_RAZOR_SNAPSHOT_READ_TOKEN.
4. Feed KLineChart only from the server-side bridge/canonical cache.
5. Add local-cache provenance fields to data diagnostics.
6. Keep CN intraday writes blocked until timestamp/finality semantics qualify.
7. Consider Parquet/DuckDB/Zstd columnar storage for large historical research datasets; SQLite remains the small, durable V0.1 cache.

## Local synthetic benchmark

Environment: Windows development workstation, Python 3.12, synthetic single-symbol 1m bars. This is a micro-benchmark, not a production capacity claim.

- 50,000 settled bars inserted in about 0.94 seconds (~53k bars/s)
- latest 500 bars read in about 4.9 ms
- serialized payload: 15.8 MB raw -> 10.5 MB zlib payload (~0.66 ratio)
- SQLite file/index/page footprint after the run: about 25.0 MB

Conclusion: SQLite is suitable for a small durable hot/warm cache, but multi-year full-market minute history should be benchmarked with a columnar or dedicated time-series store (for example Parquet + Zstd/DuckDB or an independently qualified local engine).
