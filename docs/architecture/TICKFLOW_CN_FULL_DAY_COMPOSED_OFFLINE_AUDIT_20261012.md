# TickFlow complete-session AND OHLCV parity (2026-10-12)

**Offline compositional research only. Never paid data or source admission.**

The existing modules separately check (1) one provider's A-share minute
session grid (#597) and (2) TickFlow/reference OHLCV alignment
(`scripts/tickflow_offline_bar_crosscheck.py`). These alone allow a misleading
case where **both data sources omit the same minute bar** and appear in exact
agreement. The new wrapper composes both existing checks to catch that case.

## Input and gates

Supply curated, already-normalized JSON fixtures in existing
`stock_razor_cn_offline_bar_fixture_v0_1` format; only 15m or 60m,
`BAR_END`, `NONE` adjustment, share-volume units, SH/SZ ETF identity.
Two distinct source labels are needed: TICKFLOW plus TENCENT/EASTMONEY.

An operator must independently confirm the exchange's regular trading
session and TickFlow's bar-end timestamp convention. The program cannot
verify either assertion merely because a CLI flag is present.

Run with private locally prepared fixture files, *not* in a public CI step:

    python scripts/tickflow_offline_full_day_audit.py \
        --tickflow-fixture <tickflow-fixture.json> \
        --reference-fixture <reference-fixture.json> \
        --trading-day 2026-10-09 \
        --trading-session-confirmed \
        --timestamp-semantic-verified

The single-day grid must contain 16 complete 15m bar ends or four complete
60m bar ends for the SH/SZ regular 09:30–11:30 and 13:00–15:00 session.
The separate reference comparison checks every aligned OHLCV field and
source/unit consistency. An overlap threshold of four permits detection of
missing bars common to both sources; overlap **never** qualifies completeness
on its own. Invalid/mismatched, off-grid, lunchtime, duplicate and partial
days are blocked.

## Non-admissions and limitations

Even a perfect REAL_CAPTURED-labelled pair returns only `REVIEW_ONLY`,
because the fixture origin is **self-declared** and neither independent
provider provenance, true data currentness, bar closure, PIT chronology,
coverage of a full year, nor WebSocket recovery is established. Synthetic
fixture agreement explicitly yields `SYNTHETIC_TEST_ONLY`.

The wrapper performs **zero requests**, reserves zero provider quota, writes
no canonical bars and cannot place broker orders. It returns aggregate
counts but never raw OHLCV values, provider credentials or account details.
Actual AWS TickFlow batches still require separate verified subscription
entitlement, billing/charge ceiling, transport approval and data acceptance.

PAPER_AUTO_READY=NO; RADAR_ADMISSION=BLOCKED;
SOURCE_ARBITER_ADMISSION=BLOCKED; LIVE_TRADE=NO.
