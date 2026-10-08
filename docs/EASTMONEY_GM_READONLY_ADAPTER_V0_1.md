# Eastmoney/gm read-only adapter V0.1

`data_provider.eastmoney_gm_market_data_adapter.EastmoneyGMMarketDataAdapter`
implements the existing `MarketDataAdapter` contract for mainland China
stocks and ETFs.

Supported offline/ request-response surface:

- `history_n` for bounded Daily, 60m, 15m, and other supported gm frequencies;
- `history` for explicit time windows; end-only queries use bounded `history_n`
  with `end_time` formatted in Asia/Shanghai, avoiding an invalid empty StartTime;
- `current` for a read-only quote snapshot;
- canonical `600519.SH` / `159611.SZ` symbols mapped to `SHSE.600519` /
  `SZSE.159611`;
- explicit `bob`/`eob` handling in `Asia/Shanghai`, normalized to UTC in
  `Bar`, including OHLCV and amount;
- existing `MarketDataHealth` quality flags and in-memory request deduplication;
- existing `StockRadarProviderRuntime` remains the read-only Radar consumer and
  remains the persistence boundary for research state.

Run the existing Radar entry point with `--provider eastmoney --market cn`.
Pass one or more `--symbol` values and the normal `--run-id`, `--output-dir`,
and `--database` arguments. The runner uses the same Eastmoney adapter for
1m→15m/60m Radar aggregation and Daily history. It emits the existing Radar
JSON/Markdown plus `cn_stock_radar_read_only_market_facts.json`; that JSON is
the main-control/ChatGPT read-only export and contains symbol, timeframe,
`bob`/`eob`, OHLCV, amount, provider, freshness, currentness, quality, and
status. ChatGPT should read that file (or the configured read-only artifact
transport) rather than a provider token or a trading API.

The optional `from_environment()` constructor reads only
`EASTMONEY_GM_TOKEN` (or the caller-selected environment variable), passes it
to gm, and never stores or logs the token. No order, account, or trading API
is imported.

Live `subscribe`, EOB callback latency, entitlement/finality, reconnect, and
full-session continuity are intentionally `UNKNOWN/BLOCKED` and require a
separately authorized post-holiday live qualification. Offline fixtures are
contract tests only; they are not provider or production evidence.
