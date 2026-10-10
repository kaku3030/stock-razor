# TickFlow ↔ Eastmoney/Tencent offline historical-bar crosscheck V0.1

**Status: code/test harness only. No real TickFlow bar dataset was captured, imported, or compared in this PR.** The previous AWS Premium probe returned only 3 rows per K-line request, with `schema_qualified=false`, `freshness=NOT_VERIFIED`, `closure=NOT_VERIFIED`. Its redacted logs **do not contain raw OHLCV** and cannot be reconstructed into a real-data fixture. A green CI test using synthetic rows is **not** evidence of a live TickFlow feed.

## Goal and safety

`scripts/tickflow_offline_bar_crosscheck.py` compares two **locally provided** strictly normalized JSON fixtures without SDK, cloud, provider requests, credentials, or network calls. All outputs are aggregate statistics and SHA-256 of the local input files, not raw market data. It does not select a source, write canonical data, trigger Radar, or trade.

### Accepted fixture contract

Both files must have exactly these top-level keys:

```json
{
  "schema": "stock_razor_cn_offline_bar_fixture_v0_1",
  "fixture_origin": "SYNTHETIC",
  "source": "TICKFLOW",
  "symbol": "159611.SZ",
  "timeframe": "15m",
  "timestamp_semantic": "BAR_END",
  "adjustment": "NONE",
  "volume_unit": "SHARES",
  "rows": [
    {
      "bar_end_utc": "2026-10-09T01:45:00+00:00",
      "open": 1.5, "high": 1.51, "low": 1.49, "close": 1.502,
      "volume": 10000
    }
  ]
}
```

The reference file has `source: "TENCENT"` or `"EASTMONEY"`, matching symbol/timeframe, and independently obtained rows. `fixture_origin` may be `SYNTHETIC` or `REAL_CAPTURED`; **this label is supplied by the operator and is not independently verified by the tool**. The report always states `provenance_verified=false` and `data_qualification=NOT_VERIFIED`.

**Only use the REAL_CAPTURED label after manually confirming:**
- Same ETF, exchange, actual trading session and exact bar-end UTC semantics on both providers.
- Same unadjusted price convention and same volume units (**shares**, not hands/lots or turnover).
- Same set of **completed** 15m/60m bars (exclude current unclosed bars); use a trading-day calendar to handle holidays and special sessions.
- Capture independent TickFlow and reference samples legally and locally, remove all tokens/accounts/identifiers and other unnecessary provider fields, and **do not commit raw provider payloads or licensed data**. Keep provenance and capture evidence privately.
- Align at least 10 common bars by default (recommended several sessions); inspect `missing_in_tickflow`, `missing_in_reference`, and OHLCV mismatch counts. One provider's errors do not prove the other's correctness.

Example (on a machine where you have prepared both sanitized fixture files):

```bash
python3 scripts/tickflow_offline_bar_crosscheck.py \
  --tickflow-fixture /private/tickflow_159611_15m.json \
  --reference-fixture /private/tencent_159611_15m.json \
  --min-overlap 10
```

The CLI exits 0 only for full comparison agreement of fixtures **self-labeled** real; synthetic agreement is `SYNTHETIC_TEST_ONLY` and does not exit 0. An observational match still does not establish TickFlow entitlement, freshness, continuous WebSocket stream, trading-calendar completeness, bar closure, or source admission. All source arbiter, Radar, and live-trade gates remain BLOCKED.

## Next phase (separate, explicitly authorized step)

1. Collect real TickFlow and Tencent/Eastmoney bar samples from the same **closed historical periods** with explicit provider entitlement and no surprise API spend.
2. Confirm source-specific timestamp and volume semantics before creating normalized fixtures. Never infer `BAR_END` from an unlabeled SDK field.
3. Run the offline comparator locally and retain its aggregate report with SHA-256 of both inputs; optionally test multiple symbols/sessions and holiday/half-day handling.
4. Investigate discrepancies; independently qualify closure, data freshness and WebSocket continuity before even considering shadow integration. No automatic promotion from this harness.

## Existing cloud evidence

The Oct 9 AWS Premium REST smoke verified endpoint responses for quotes, minute bars and depth, but **did not** prove production-quality data; the WebSocket smoke observed no events in 15 seconds. The latest cloud TickFlow MCP work only reads sanitized probe metadata.
