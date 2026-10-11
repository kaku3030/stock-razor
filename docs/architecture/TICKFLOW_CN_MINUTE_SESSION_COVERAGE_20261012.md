# TickFlow A-share minute history grid audit — 2026-10-12

**Research-only, offline, no paid requests.**

The merged #581/#585 history batch contract checks request echoes, source
consistency, timestamp ordering and a provider-supplied `window_complete`
boolean, but the boolean alone cannot prove complete A-share minute bars.
Before TickFlow Primary Source promotion, a separate **session grid** check
must independently detect missing and extra interval labels.

The new `review_a_share_minute_session` accepts only caller-supplied
sanitized `HistoryRow` metadata. For a confirmed regular SH/SZ trading day,
it derives 09:30–11:30 and 13:00–15:00 local Asia/Shanghai intervals;
expected per-symbol full-day counts are 240/48/16/8/4 for
1m/5m/15m/30m/60m. **BAR_START** and **BAR_END** semantics are explicit,
and must be independently verified before use. It refuses duplicates,
missing labels, extra lunch/off-grid timestamps, invalid timezone/source,
unknown symbol, or excessive batches. It does not assume a weekday is
automatically an open trading day: caller must separately confirm the
exchange session, including holiday closures.

A fully covered grid earns only `REVIEW_ONLY`, not `PASS` for
primary source or data/currentness promotion. This is timestamp coverage,
**not** independent price accuracy, OHLC/volume parity, provider billing,
calendar provenance, WebSocket live stability, interruption recovery,
full-year coverage, or PIT OOS qualification.

### Next live cloud acceptance blockers

1. Verify paid Expert account entitlement and exact per-request charges,
   shared durable global reservation and independently approved ceilings.
2. Acquire one bounded, supervised AWS historical batch for a confirmed
   regular trading day (only after separate charge approval).
3. Verify whether TickFlow minute timestamps label bar start or bar end,
   then qualify grid counts and missing/duplicate/off-grid bars.
4. Compare sanitized TickFlow OHLCV and continuity to the independently
   sourced Tencent/Eastmoney historical day; record disagreements.
5. Test selected full-year windows and trading-session calendars; only then
   discuss Primary Source admission.

All network/provider requests, reservations, broker mutations, orders and
deployment are **out of scope** for this PR.

`PAPER_AUTO_READY=NO`
`RADAR_ADMISSION=BLOCKED`
`SOURCE_ARBITER_ADMISSION=BLOCKED`
`LIVE_TRADE=NO`
