# TickFlow A-share operator guide (research only)

**As of 2026-10-23.** This is an operator procedure for the isolated TickFlow cache. It does not promote a data source, Radar signal, paper workflow, or trading gate.

## Current verified state

The live cloud readback at 2026-10-23 09:55 JST reports:

- Radar worker SHA: `286e5a6e607bfd3cf8a39fb8e00e25d033efa2a3`.
- TickFlow collector SHA: `31398415051e1662ce3f85c8253c3abbc9889859`.
- Four research ETFs: `159611.SZ`, `159209.SZ`, `512730.SH`, `159363.SZ`.
- Each symbol has 60 daily, 24 hourly, and 96 fifteen-minute rows. All report `TICKFLOW_PREMIUM`; the fallback source is null.
- Latest stored intraday label is 15:00 China time on 2026-10-22. During the 2026-10-23 pre-open readback, the cache poll was unchanged; that is expected outside the CN session.
- The worker evaluation is PASS for historical research. Intraday timestamp/currentness remain UNPROVEN; bar finality remains NOT_VERIFIED; permissions remain `record_only` and `RADAR_ADMISSION=BLOCKED`.

The 24 hourly rows are not enough for a 60-hour moving average or a 100-bar hourly profile. Do not present current technical output as a warmed-up strategy evaluation.

## What the provider has confirmed in writing

The support replies dated 2026-10-08, 2026-10-13 and 2026-10-20 say:

- Expert covers the listed A-share minute intervals and read-only research use from AWS Tokyo is permitted.
- The user's monthly Expert plan is understood to include unlimited requests. Support also says request rate and WebSocket subscription totals are account-level, but supplied no numeric technical throttling ceiling. Treat plan billing/entitlement separately from service rate limiting; back off on 429.
- Intraday K-line labels are BAR_END. Daily bars use 00:00 date labels.
- There is no `is_final` or `closed` field. Once the next K-line forms, the prior bar can be treated as operationally closed; this does not establish immutable exchange finality.
- A 13:01 lunch-period prefilled bar may have unchanged OHLC and zero volume. The vendor says the same timestamp behavior applies to `klines.get` and `klines.intraday`.
- If data is delayed, the support recommendation is to re-fetch at two-minute intervals. Values may be corrected about an hour after close; support recommends a post-close pull after 20:00 Beijing time.
- Tiny JSON float inconsistencies should be validated with the vendor's stated tolerance, not by altering the original price fields.

Preserve the original email thread as the source evidence. These confirmations do not supply a signed finality seal, numeric historical retention/max-window values, or a guaranteed correction cutoff.

## Routine validation

### During a China session

1. Read the TickFlow-specific private research observation, not generic market bars that may use Eastmoney/Tencent.
2. Record observation time, collector SHA, worker SHA, source/cache sequence, source age, symbol set, provider lineage, per-frame row counts and latest labels.
3. Check expected session grid for the actual exchange calendar, including the lunch interval. For a full regular session, expected counts are 240/48/16/8/4 for 1m/5m/15m/30m/60m; do not infer that a weekday is a trading day.
4. Check duplicate, missing, late and out-of-order labels. A label at an expected boundary is not itself proof that the bar has arrived, is operationally closed, or is final.
5. For operational research closure, apply the vendor successor rule only when the next same-provider bar is present on the correct session grid. Keep `bar_finality=NOT_VERIFIED`.
6. During RTH, evaluate source age and sequence advancement. A fresh worker heartbeat with an unchanged upstream sequence does not prove live bar delivery.

### After close and corrections

1. After the vendor-recommended correction window (after 20:00 Beijing time), take a second bounded TickFlow-only read.
2. Compare rows by provider, symbol, timeframe and bar-end label. Preserve both observations and append a revision record; never overwrite the earlier snapshot silently.
3. Record revised-row counts and sanitized reason codes. Keep raw prices and API credentials out of public logs and email.
4. Repeat across at least 10 trading sessions before considering a research-quality currentness statement. This is an evidence target, not an admission criterion.

### History depth

Use explicit `start_time` and `end_time` when testing historical windows. Store the requested window alongside returned first/last labels and row count. Do not infer that a successful request returned the entire window. The current 60/24/96-row cache supports a bounded observation only; request enough history for every indicator and protocol lookback, then verify multi-day labels and session completeness.

The approved monthly Expert subscription permits the user's research plan; still obey account-wide rate limiting. Prefer batch reads, reuse the existing worker/connection, avoid polling historical windows, and back off on 429. Never add a second high-frequency collector to work around an account-level limit.

## Evidence labels

| Result | Meaning |
| --- | --- |
| Worker heartbeat PASS | Worker is alive and its readback is available |
| Evaluation PASS | The bounded historical research evaluation ran |
| `TICKFLOW_PREMIUM`, no fallback | TickFlow supplied the cached frame |
| New successor bar + correct grid | Supports operational closure under the vendor rule |
| Stable post-close second snapshot | Supports a revision observation for that interval |
| `bar_finality=NOT_VERIFIED` | No immutable provider/exchange finality evidence |
| `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO` | Safety gates remain closed |

A CI pass, deployment pass, entitlement/quote right, heartbeat, or technical analysis status cannot substitute for these evidence layers. Do not relax the gates in this procedure.

## Current follow-up to TickFlow Support

A draft follow-up asks only for the still-missing historical-window contract and numeric account-level request-rate guidance. The previous vendor answers already cover BAR_END, successor operational close, lunch prefill and post-close correction advice; do not ask those questions as if unanswered.
