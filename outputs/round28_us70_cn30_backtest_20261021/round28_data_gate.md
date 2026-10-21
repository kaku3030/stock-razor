# Round28 70 US + 30 A-share data gate

Status: **BLOCKED**

- Data files present: 140/500 (28.0%).
- US: 140/350 files; 42 symbols have at least one missing timeframe.
- A-shares: 0/150 files; 30 symbols have at least one missing timeframe.
- Local OpenD history quota: 72 used, 28 remaining; 42 missing US symbols exceed remaining quota by 14.
- Local TickFlow A-share historical cache: not found in the inspected local capture/cache roots.
- Provider calls made by this audit: 0. It only checked local filenames and file sizes.

## Blockers

- LOCAL_OPEND_HISTORY_QUOTA_INSUFFICIENT_FOR_MISSING_US_SYMBOLS
- LOCAL_TICKFLOW_CN_HISTORICAL_CACHE_MISSING
- POINT_IN_TIME_UNIVERSE_MEMBERSHIP_UNVERIFIED
- OFFICIAL_S2_RULE_UNAVAILABLE

## Interpretation

This is a candidate-universe and input-availability audit, not a strategy backtest. Round27 results for 30 US names cannot be relabeled as a 70 US + 30 A-share result. S2 remains an unvalidated candidate because its official frozen rules are unavailable. No USD and CNY P&L, costs, or drawdowns are combined.

See `round28_data_gate_status.json` for the per-symbol/timeframe missing-input list.
