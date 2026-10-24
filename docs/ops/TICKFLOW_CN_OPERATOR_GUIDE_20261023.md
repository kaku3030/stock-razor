# TickFlow A-share operator guide (research only)

> Hybrid V1.0 update: Windows TickFlow local acceptance follows [the current local procedure](TICKFLOW_WINDOWS_LOCAL_ACCEPTANCE.md). AWS TickFlow pairing is no longer a requirement. The older evidence below retains its original scope.

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

## Morning regression found on 2026-10-23

Read-only AWS audit [39901934538](https://github.com/kaku3030/stock-razor/actions/runs/39901934538)
found `S0_60M_NORMALIZE / ROW_COUNT_BELOW_MIN`, with the private cache BLOCKED
and the Radar consumer returning `MISSING_EVALUATION`. The earlier pre-open
historical PASS above does not establish current-session availability.

Historical warmup and the current-session increment have different row-count
contracts: keep the historical four-row validation floor, but allow an empty
or one-to-three-row intraday increment before all four hourly bars have formed.
Validate every returned row and quarantine future/forming labels before merging
by label; never manufacture missing bars or promote finality/currentness.
The same distinction applies to short 1m/5m diagnostic increments near open.

When evaluation is absent, the reader exposes a separate `worker_heartbeat`
with FRESH/STALE/INVALID, worker SHA, sequence, emission time and poll status.
FRESH indicates only an observed recent worker heartbeat; analysis remains
INVALID, and source currentness, bar closure and all trading gates are independent.
Raw exception messages and provider payloads are not exposed.

## D1 cutoff and explicit session reader

A follow-up read after the collector update found 59 D1 rows: the requested
60 included today's 00:00 date-stamped forming candle, which normalization
correctly quarantined. D1 historical requests now end one millisecond before
today's Shanghai midnight, leaving all 60 requested slots for prior dates.
No request count or raw reader limit is increased; no missing bar is fabricated.

Use `get_cn_market_data(symbol="TICKFLOW:SESSION", limit=1)` for one aligned
four-symbol × five-period session-progress read. Intraday frames use the existing
strict due-grid reader; D1 remains historical-only. The existing `TICKFLOW:FULL`
route retains its historical-only contract, including rejection of same-day
vendor-float rows before the post-close window. Do not use FULL's rejection as
proof of a provider outage when the required mode is session progress.

The Radar bridge explicitly uses session progress when the source contains
today's intraday rows; otherwise it reports bounded historical research.
A missing due boundary is still blocked, with no historical retry masking it.
Both modes keep currentness UNPROVEN, all candles partial, immutable finality
NOT_VERIFIED and signal permission record_only. `PASS_SESSION_PROGRESS_ONLY`
is cache/grid research evidence, never a confirmed trading signal.

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
