# TickFlow A-share: bar-end time vs provider-confirmed finality

## Finding — 2026-10-16 during the live A-share session

At 10:51 JST the existing AWS read-only TickFlow cache showed today's
`09:35/09:40/09:45/09:50` 5m labels and the first `09:45` 15m label
for `159611.SZ` and `518880.SH`. The 15m snapshots carried sequences
223/224 with cache ages under 15 seconds; the independent AWS SSM audit
run `38837829567` later showed a 15m due-grid present for both and
worker sequence 242 → 246, with active worker and fresh private cache.

**However, these facts do not mean an exchange-final 15m bar.**
Both `normalize_bars()` and `read_cn_tickflow_research_data()` in
`data_provider/cn_tickflow_research_cache.py` intentionally set
`is_partial_bar=True`, `bar_finality=NOT_VERIFIED` on **all** rows.
This is a deliberate fail-closed research contract, not a skipped
line of code or a loop bug. Changing the flag just because the
clock reached 09:45 would invent provider finality.

The upstream TickFlow public Python SDK
`tickflow/resources/klines.py` documents the `klines.get(...,
as_dataframe=False)` compact response columns as
`timestamp/open/high/low/close/volume/amount`. **No authenticated
`is_closed`, candle revision, server close-ACK or exchange-sealed
finality field was identified in that K-line response contract.**
The current AWS worker makes four/supplemental bounded provider
K-line requests per poll, without independently signed finality metadata.
It cannot manufacture that information at its cache layer.

Official public SDK source:
https://github.com/tickflow-org/tickflow/blob/main/tickflow/resources/klines.py

## New strictly separated offline qualification

`data_provider/tickflow_bar_stability_audit.py` adds a pure read-only
two-observation shadow auditor using the **already-collected** private
research snapshots. It requires:

- Exact TickFlow Premium / research-only / closed admission gates /
  matching 40-hex repo SHA, monotonically increasing cache sequences.
- Two independently published observations, 10–300 seconds apart,
  both **after** the target 5m/15m/60m exchange-grid boundary plus
  a 90-second grace, with fresh second observation.
- One matching valid strict-OHLC row in both snapshots and equal
  OHLCV+turnover digests, without leaking prices or raw provider data.
- Any mutation, invalid revision, same-sequence replay, wrong session
  clock, vendor-float tolerance or malformed row fails closed.

This can emit
`STABLE_AFTER_MATURITY_NOT_VENDOR_FINAL` or
`ROW_MUTATED_AFTER_MATURITY`; **neither is a provider seal**.
The output always states:

`bar_finality=NOT_VERIFIED`,
`exchange_bar_finality=NOT_VERIFIED`,
`provider_finality_attestation=NOT_AVAILABLE_IN_KLINES_SCHEMA`,
`RADAR_ADMISSION=BLOCKED`, `SOURCE_ARBITER_ADMISSION=BLOCKED`,
`LIVE_TRADE=NO` and no provider requests or writes.

The shadow audit does not overwrite any existing cached bars, upgrade
readers, change installed worker, create new paid API calls or deploy.

## The true missing external contract (P0)

Before *any* provider-final bar may be admitted, obtain documentary and
on-AWS independent confirmation from TickFlow for:

1. **Timestamp semantics:** K-line `timestamp` denotes bar start or
   bar end? Confirm 09:30–09:45 mapping and exchange break rules.
2. **Finality:** Does each returned minute K-line represent a finalized
   exchange bar only after its time interval has elapsed, or may the
   provider revise it later? Is there a producer/server confirmation
   event/field that uniquely attests to bar close?
3. **Correction/revision mechanism:** If 09:45 OHLCV/amount changes at
   09:47 or after reconnection, what source revision/sequence/clock
   identifies the corrected final value?
4. **1m→5m→15m→60m/D1 cross-period consistency** with actual
   entitlement and session calendars, including partial present bar.
5. **Version/runtime provenance:** deploy only reviewed main after CI,
   confirm same API/collector schema and independently verify EC2
   provider QOS/rights, source lag and re-connect behavior.

Until verified, source arbiter and Radar stay **BLOCKED**, even when
the present clock-grid and two-poll stability both PASS.

Proof of stable data is useful for research; it cannot be silently
promoted to trade-executable K-lines.
