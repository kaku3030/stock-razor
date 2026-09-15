# Open-Source Intake — Currentness / Continuity Harvest Batch 2026-09-09

Status: **DEFECT AUDIT / DESIGN INPUT — NON-PRODUCTION**

## 1. Why this batch exists

The imported `realtime_monitor` has a single deterministic Unified Data Health authority. That is the correct ownership direction, but its current intraday freshness rule contains a false-green gap:

- it retrieves the latest historical bar;
- extracts `latest_bar_time`;
- computes an expected trading **date**;
- returns `OK` whenever `str(latest_bar_time)[:10] == expected_date`.

For 1m/5m/15m/30m/60m data during or after an active trading session, this proves only:

> there is at least one bar dated today.

It does not prove:

> provider progress is current enough for the evaluation point.

Example defect class:

- expected/current trading date = 2026-09-09;
- latest 15m bar = 09:45;
- evaluation = 15:30 ET;
- current code can still return `OK` because both dates are 2026-09-09.

This violates the intent of the frozen Live Feed Currentness model even though the realtime monitor predates that implementation.

## 2. Existing strengths to preserve

Do not replace the whole Unified Data Health layer.

Useful existing properties:

- one central freshness authority rather than downstream re-derivation;
- trading-calendar query rather than hardcoded holiday dates;
- injected `now_et` / calendar map for deterministic tests;
- fail-closed behavior when calendar is unavailable;
- daily/weekend/premarket handling avoids naively calling last Friday stale on Saturday/Sunday;
- AI prompts are explicitly forbidden from overriding deterministic Data Health.

The defect is specifically **intraday progress qualification**, not absence of a Data Health owner.

## 3. Futu API evidence

### 3.1 Historical vs real-time candlestick surfaces

Official Futu OpenAPI documentation distinguishes:

- `request_history_kline(...)` — historical candlestick retrieval;
- `get_cur_kline(...)` — real-time candlestick retrieval for subscribed securities.

Current realtime-monitor Data Health uses the historical request surface as its bar input.

Implementation consequence:

> A historical endpoint returning a same-date bar must not, by itself, be promoted into a proof of real-time intraday currentness.

Do not silently equate "historical API returned today's row" with "live feed progress is current".

### 3.2 `time_key`

Official docs define `time_key` as candlestick time and define US values in US Eastern time, but the inspected documentation does not provide a sufficiently strong universal contract saying whether every K-line/timeframe/provider path uses start-boundary vs end-boundary semantics for Currentness qualification.

Radar's own Futu live-provider research also demonstrated provider-specific forming-bar behavior and warned against manufacturing ProgressIdentity from timestamps alone.

Therefore:

> do not freeze a generic `now - time_key <= timeframe` rule from documentation wording alone.

### 3.3 Trading day type correction

Current monitor comments describe returned trading date type as `WHOLE/HALF`.

Current official Futu documentation defines the trade-date-type vocabulary as:

- `WHOLE`
- `MORNING`
- `AFTERNOON`

The trading calendar provides date-level session type, not a complete intraday session-close schedule for every exceptional market condition.

Implementation consequence:

- stop documenting/assuming a generic `HALF` value;
- do not invent an exact US early-close boundary solely from the enum name;
- exceptional/non-WHOLE session progress needs explicit schedule authority or conservative abstention.

Official calendar documentation also notes that temporary market closures are not removed from the returned trading-day list. Calendar membership therefore cannot by itself prove `PROGRESS_EXPECTED`.

## 4. External mature methods harvested

### Apache Flink — event-time watermarks

High-value method, not dependency:

- watermark/current progress is an explicit construct;
- bounded out-of-orderness is explicit rather than guessed from receive time;
- idleness is modeled separately so a quiet source does not permanently stall/poison progress interpretation.

Radar translation:

- `CurrentnessBoundary` is analogous to an explicit progress boundary, not raw wall-clock age;
- provider publication/out-of-order tolerance must be explicit evidence/config;
- expected silence/idleness is separate from currentness failure.

Disposition: `METHOD HARVEST / NO DEPENDENCY`.

### Nautilus Trader — ordering/freshness discipline

Useful method:

- do not infer exact data delivery order merely from stored/catalog timestamps;
- preserve correlation/identity and freshness semantics at event boundaries;
- transport/data event mechanics remain distinct from strategy interpretation.

Radar translation:

- provider source time is evidence, not automatic delivery order;
- `received_at` cannot manufacture source progress;
- Currentness/Continuity must use provider-semantic progress identity where available.

Disposition: `METHOD HARVEST / TEST-REUSE`.

## 5. Currentness design decomposition

Do not have one boolean `fresh` computation silently answer several different questions.

Candidate fact decomposition for later implementation:

1. `CALENDAR_ALIGNMENT`
   - Is the latest evidence on the expected trading date/session domain?

2. `PROGRESS_IDENTITY`
   - What provider-semantic value can be compared for progress?
   - `PROVABLE / UNPROVABLE / UNKNOWN`.

3. `CURRENTNESS_BOUNDARY`
   - What minimum progress is expected at this evaluation point?
   - Depends on session/trading expectation/provider semantics/clock trust.

4. `CURRENTNESS`
   - `PROVEN / NOT_PROVEN / INDETERMINATE`.

5. `CONTINUITY`
   - separate Phase-2 proof using a later independent progress opportunity.

6. `TRADING_EXPECTATION`
   - `PROGRESS_EXPECTED / SILENCE_EXPECTED / UNKNOWN`.

7. `SESSION_PHASE`
   - active / expected-silence / closed semantics supplied by a calendar/session authority.

This mirrors the frozen Live Feed design rather than creating a competing monitor-only freshness model.

## 6. Immediate false-green rule

Freeze as a safety requirement before realtime-monitor production promotion:

> Same trading date alone is insufficient to return `OK` for an intraday timeframe when current-session progress is relevant.

This is a negative invariant and does not require a numeric timeout.

A safe interim implementation may return a fail-closed currentness status (for example `CURRENTNESS_UNVERIFIED`) until provider-semantic progress can be positively qualified.

It is better to expose unknown currentness than to label same-date stale evidence healthy.

## 7. Daily vs intraday separation

### Daily / 1D

Date/session alignment can remain a meaningful primary currentness fact because the expected progress unit is one trading date, subject to calendar authority.

### Intraday

Date equality is only a prerequisite.

To prove intraday currentness, later implementation must additionally establish a provider-semantic progress boundary.

Do not reuse the daily rule unchanged for intraday timeframes.

## 8. Why a simple age threshold is rejected

Candidate rejected shortcut:

```text
if now - latest_bar_time > 2 * timeframe:
    STALE
```

Reasons:

- K-line timestamp boundary semantics are provider/timeframe specific;
- temporary market closures are not necessarily represented by date membership;
- legitimate zero-trade silence may exist;
- premarket/after-hours/closed-session expectations differ;
- provider publication delays/out-of-order behavior need explicit tolerance;
- source clock trust matters;
- historical/backfill evidence can arrive recently without being current.

Elapsed age may become one input after provider semantics are proven, but it is not the whole contract.

## 9. Continuity design implication

A single current-looking bar cannot establish stable recovery.

Future monitor/LiveFeed convergence should retain the frozen two-phase model:

```text
CURRENTNESS_PROVEN
    -> later independent provider progress
    -> CONTINUITY_PROVEN
    -> LIVE/data-authority eligible
```

Duplicate same-progress update, correction at same progress, or generic transport heartbeat does not count as Phase 2.

This directly protects against the "one fresh callback after reconnect, then silence" failure class.

## 10. Legacy realtime-monitor repair recommendation

Do **not** write a second permanent Currentness engine inside the monolithic monitor.

Preferred sequence:

1. add regression tests proving same-date-but-hours-old intraday data cannot be `OK`;
2. correct trade-date-type vocabulary assumptions;
3. introduce an explicit fail-closed `CURRENTNESS_UNVERIFIED`/equivalent path for intraday cases where only date alignment is proven;
4. preserve existing daily/calendar behavior;
5. later route realtime monitor to the shared LiveFeed/Data Health Currentness contract as it becomes available;
6. remove/retire monitor-local currentness logic rather than maintaining two competing engines.

This keeps the immediate safety repair small while preventing architectural duplication.

## 11. Required regression cases

At minimum:

1. 15m same date, latest bar hours behind during active session -> **not OK**;
2. 1h same date, morning-only old bar after regular close -> **not OK**;
3. daily bar on expected latest trading date -> date-currentness still allowed under calendar authority;
4. weekend/premarket where previous trading date is legitimately expected -> not falsely stale merely due date gap;
5. calendar unavailable -> fail closed as today;
6. non-WHOLE trade date type -> do not invent unsupported exact session boundary;
7. temporary closure/calendar ambiguity -> no progress-success inference from date membership alone;
8. future/ahead-of-expected date -> fail closed;
9. malformed/unparseable bar timestamp -> fail closed;
10. downstream AI cannot override currentness status.

## 12. External dependency decision

No new runtime dependency is justified.

- Flink: methodology only.
- Nautilus Trader: methodology/test reference.
- Futu official APIs: provider evidence and future adapter surface, not currentness authority by themselves.

Currentness quality comes from better contracts/evidence, not another framework.

## 13. Promotion state

`DEFECT VERIFIED -> DESIGN INPUT`.

No production fix is claimed by this document.

Because `realtime_monitor` currently lives in the still-open Stock Razor migration PR, the preferred code repair should be made as a narrow follow-up/stacked fix after the migration base is stable, with its own independent validation rather than hiding the correction inside the large migration diff.

## Governing sentence

> "Today" is a date. Currentness is a progress claim.