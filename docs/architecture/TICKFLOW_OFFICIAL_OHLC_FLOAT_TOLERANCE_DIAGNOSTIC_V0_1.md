# TickFlow historical OHLC precision evidence V0.1

## Evidence triggering this change

The independently triggered AWS research read-only audit [38455085359](https://github.com/kaku3030/stock-razor/actions/runs/38455085359) completed its SSM execution, but its actual cache was blocked: `S0_15M_NORMALIZE`, `OHLCVA_HIGH_LT_BODY`, both snapshots `BLOCKED_VALUE_ERROR`. All four TickFlow Kline research readers returned `INVALID_CACHE`. An AWS shell exit code of zero **did not** mean data quality had passed.

TickFlow Support's October 13, 2026 reply described a JSON floating-point tolerance using an **absolute** `1e-5` bound on `max(open, close, low) - high` and `low - min(open, close, high)`; do not substitute the ETF `0.001 CNY` tick or basis points.

## Deliberate narrow behavior

The private historical OHLC rejector computes the larger of those two discrepancies in `Decimal(str(value))` arithmetic, comparing the absolute discrepancy with `0.00001`. It annotates the existing strict `ValueError` with only `WITHIN_1E_MINUS_5`, `OVER_1E_MINUS_5`, or `UNKNOWN`. The worker persists a **fixed enum only**, and the cloud read-only audit explicitly allowlists the exact same enum. There are no prices, source times, symbol IDs, account data, raw provider payloads, or exception strings in public evidence.

**No** OHLC value is rewritten, rounded, tolerated as a valid historical bar, made final, promoted into canonical cache, or allowed through source/Radar/Paper/trading admission. A historical OHLC defect *still blocks* the research snapshot; this is diagnostic evidence for a later independently reviewed provider contract remedy. A cloud deploy of the worker is required before live diagnostics can differ from `UNKNOWN`.

## Evidence gate and rollback

Test both sides of the vendor `1e-5` threshold and the high/low violation classes. Only a new exact-main deployment and SSM two-sample audit can establish the magnitude bucket for real AWS TickFlow feed failures; CI alone does not. Rollback this isolated diagnostic change without changing prior source, pricing, or risk semantics.
