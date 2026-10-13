# TickFlow historical OHLC precision evidence V0.1

## Evidence triggering this change

The independently triggered AWS research read-only audit [38455085359](https://github.com/kaku3030/stock-razor/actions/runs/38455085359) completed its SSM execution, but its actual cache was blocked: `S0_15M_NORMALIZE`, `OHLCVA_HIGH_LT_BODY`, both snapshots `BLOCKED_VALUE_ERROR`. All four TickFlow Kline research readers returned `INVALID_CACHE`. An AWS shell exit code of zero **did not** mean data quality had passed.

TickFlow Support's October 13, 2026 reply described a JSON floating-point tolerance using an **absolute** `1e-5` bound on `max(open, close, low) - high` and `low - min(open, close, high)`; do not substitute the ETF `0.001 CNY` tick or basis points.

## Reviewed research-only acceptance of the vendor float contract

In the subsequent guarded research-only adjustment, an OHLC violation is accepted **only when the strict raw high/low inequality is fully explained by an absolute gap <= `0.00001` CNY**, using `Decimal(str(original_json_number))` math as confirmed by TickFlow Support. No rounding, quote rewrite, synthetic high/low, inferred volume, or bar-finality promotion occurs.

A retained raw row gets an explicit `ohlc_validation=VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY` tag. The PRIVATE research reader independently revalidates that exact threshold; a missing/forged tag, mismatch, non-positive OHLC, negative volume, or a gap greater than `1e-5` remains `INVALID_CACHE` or rejected/quarantined by the original worker. Strictly valid rows retain the `STRICT` tag. All exposed rows remain `is_partial_bar=true` and `bar_finality=NOT_VERIFIED`. Source arbitration, Radar, Paper and live trading stay blocked. This is **not** authorization to publish canonical data or generate signals.

This follows the vendor's stated OHLC serialization tolerance but does **not** solve historical continuity, BAR_END-to-exchange-finality evidence, overnight revision (~1 hour after close), independent price parity, or data-provider admission. Cloud validation still needs the separately authorized TickFlow AWS worker deployment and source-provenance audit. The behavior is deliberately scoped to the TickFlow research reader and can be reverted without touching provider credentials or any trading service.

## Deliberate narrow behavior

The private historical OHLC rejector computes the larger of those two discrepancies in `Decimal(str(value))` arithmetic, comparing the absolute discrepancy with `0.00001`. It annotates the existing strict `ValueError` with only `WITHIN_1E_MINUS_5`, `OVER_1E_MINUS_5`, or `UNKNOWN`. The worker persists a **fixed enum only**, and the cloud read-only audit explicitly allowlists the exact same enum. There are no prices, source times, symbol IDs, account data, raw provider payloads, or exception strings in public evidence.

**No** OHLC value is rewritten, rounded, tolerated as a valid historical bar, made final, promoted into canonical cache, or allowed through source/Radar/Paper/trading admission. A historical OHLC defect *still blocks* the research snapshot; this is diagnostic evidence for a later independently reviewed provider contract remedy. A cloud deploy of the worker is required before live diagnostics can differ from `UNKNOWN`.

## Evidence gate and rollback

Test both sides of the vendor `1e-5` threshold and the high/low violation classes. Only a new exact-main deployment and SSM two-sample audit can establish the magnitude bucket for real AWS TickFlow feed failures; CI alone does not. Rollback this isolated diagnostic change without changing prior source, pricing, or risk semantics.
