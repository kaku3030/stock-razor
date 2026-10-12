# US OpenD 2026-10-12 shared K1M hole — no-provider triage

Status: **OBSERVED IN CLOUD CACHE; ROOT CAUSE UNKNOWN.** Research only.
This is not an AWS diagnostic, data repair, real-time source promotion or
permission to run any broker action.

## Direct read-only cloud observation

On 2026-10-13 JST, the connected STOCK_RAZOR cloud-local read-only
`get_market_bars(symbol, timeframe=1m, limit=450)` returned **nine out
of nine** configured US OpenD symbols with the same missing minute start:
**2026-10-12 14:58:00 UTC = 10:58:00 America/New_York**.

AMD, NVDA, TSLA, AAPL, QQQ, GLDM, LITE, AAOI and CIEN each had 388
canonical 1m regular-session bars from 13:30 through 19:58 UTC inclusive.
All nine sequences jumped directly from bar start 14:57 UTC to 14:59 UTC.
The 20:00 session-close minute was **not** counted as an interior hole
because a later independently stamped canonical minute was not present.

Observed LiveFeed heartbeat was active/CONNECTED and its QOT_RIGHT query
had PASS/LV3, but global bar_closure remained UNPROVEN, canonical snapshot
status STALE outside the quoted main regular session, and AWS runtime SHA
was still `c777739bc277022f258faf2599222215e9640231`.
Protected source `main` has since advanced. These are **not**
independent proof of healthy ingestion for 10:58 ET.

An affected AMD 15m bucket around the gap was marked
`is_complete=false` with `MISSING_BAR`. A callback count or an
apparently good following bar cannot erase this fact. The common gap
suggests inspecting upstream stream/router, queue loss, reconnect timing,
history-catchup and any shared writer phase; it does **not** establish
which component was responsible.

## Deterministic candidate correlation only

`audit_shared_us_k1m_interior_gaps` accepts already-supplied 1m canonical
Bar records from **at least two named US symbols**. It verifies:
- exact symbol identities, provider=futu, feed=opend, regular-session
  provenance and interval-end source timestamps;
- genuinely closed/complete 1m intervals with no duplicates or malformed
  provenance;
- one timezone-aware NY market session with a shared interval of
  independently observed bars;
- only **interior** slots, excluding a current forming minute and any
  trailing boundary without a later provider-stamped bar.

It reports common missing minute labels with fixed statuses, preserves
all input bars, and never asks OpenD for any missing OHLCV. Even
`NO_SHARED_GAP_OBSERVED` is **not** realtime feed qualification.
`SHARED_GAP_OBSERVED` establishes correlation, not cause.

## Next legitimate root-cause verification

1. Read-only compare private EC2 LiveFeed service errors, reconnects and
   dropped-event/queue-full counters around 14:57–15:01 UTC.
2. Check provider K1M historical response for the exact minute only if
   separately approved and within quote-right/cost limits. Distinguish
   provider returned K1M vs a generated, inferred or repaired synthetic row.
3. Re-ingest a missing minute **only** through existing source-attested
   history reconciliation after timestamp, provenance, unit and duplicate
   checks; never patch SQLite/cache directly or write zero-volume bars.
4. After any reviewed fix, redo 15m/60m closed complete grids, independent
   native K5M volume/turnover parity, cache freshness and safe promotion
   assessment. Keep Radar and Paper automatic execution blocked until
   the separate source/admission gates are met.

**Always** `RADAR_ADMISSION=BLOCKED`,
`SOURCE_ARBITER_ADMISSION=BLOCKED`, `PAPER_AUTO_READY=NO`,
`LIVE_TRADE=NO`, `TRADE_EXECUTION=NO`.
