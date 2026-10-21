# Round28 70 US + 30 A-share data gate

Status: **BLOCKED**

- Data files present: 300/500 (60.0%).
- US: 300/350 files; 10 symbols have at least one missing timeframe.
- A-shares: 0/150 files; 30 symbols have at least one missing timeframe.
- Local OpenD history quota: 100 used, 0 remaining; 10 missing US symbols exceed remaining quota by 10.
- Local TickFlow A-share historical cache: not found in the inspected local capture/cache roots.
- Local OpenD A-share entitlement trial: local-opend-denied.
- Provider calls made by this audit: 0. It only checked local filenames and file sizes.

## Blockers

- LOCAL_OPEND_HISTORY_QUOTA_INSUFFICIENT_FOR_MISSING_US_SYMBOLS
- LOCAL_TICKFLOW_CN_HISTORICAL_CACHE_MISSING
- LOCAL_OPEND_CN_MARKET_ENTITLEMENT_MISSING
- POINT_IN_TIME_UNIVERSE_MEMBERSHIP_UNVERIFIED
- OFFICIAL_S2_RULE_UNAVAILABLE

## Interpretation

This gate still blocks the requested full 70 US + 30 A-share backtest. A separate 60-US-only exploratory replay has now completed using available local files; it is not a 100-name result. S2 remains an unvalidated candidate because its official frozen rules are unavailable. No USD and CNY P&L, costs, or drawdowns are combined.

See `round28_data_gate_status.json` for the per-symbol/timeframe missing-input list.

## Available-subset exploratory replay

- Completed a separate 60/70 U.S.-only replay using local QFQ/RTH captures. It includes 300 input files across D1/1H/15m/5m/1m, with ten U.S. names and all 30 A-shares excluded.
- The input audit found 467 invalid OHLCV rows across 23 symbols and 420 symbol-session pairs. Each affected full session was excluded consistently from all timeframes, strategies, and matched buy-and-hold.
- The report includes S1, S3-S6 and the Round26 S2 candidate; S2 is explicitly unvalidated because the official frozen rule is unavailable. Metrics cover 5/10/20 bps per side and full/train/OOS windows.
- This remains exploratory: current-universe survivorship and point-in-time membership, provider finality, timestamp semantics, and independent data-quality signoff are unresolved.

See ../round28_us60_us_only_exploratory_20261021/round28_us60_backtest_report.md and round28_us60_us_only_exploratory_20261021/round28_us60_six_strategy_comparison_all_costs.csv.
