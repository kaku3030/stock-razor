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
The current AWS worker fetches four eligible timeframes for each of
two pilot ETFs when supplemental periods are enabled (up to eight K-line
requests per successful poll), without independently signed finality metadata.
It cannot manufacture that information at its cache layer.

The upstream public WebSocket SDK `tickflow/resources/stream.py`
currently advertises `quotes` and `depth` channels; it does not
document a dedicated `KLINE_CLOSED` event which could independently
qualify these minute bars.

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

## Real cloud multi-timeframe readback (separate from finality)

A direct read-only AWS MCP sample at about 11:04 JST on 2026-10-16
retrieved the existing cached `TICKFLOW_PREMIUM` bars for both pilot
ETFs. It reconstructed two independent 15m bars (`09:45`, `10:00`
China-local end labels) using each corresponding three 5m rows:

- 159611.SZ: OHLC exact within 1e-5, volume exactly equal, amount
  only float rounding difference at most 1e-8.
- 518880.SH: OHLC exact within 1e-5, volume exactly equal, amount
  equal to floating precision.
- Two retrieved timeframes had fresh research caches, but every row
  still reported `is_partial_bar=true` and finality `NOT_VERIFIED`.

`audit_tickflow_5m_15m_reconciliation()` makes that integrity check
repeatable against a *single verified cache publication*, with fixed
enumerated results only and no raw bar values in output. Divergent OHLC,
volume, amount, missing rows, invalid/ambiguous provenance or vendor-float
tolerance fail closed. The output never grants provider finality, source
or Radar admission, even on perfect cross-period equality.

## Confirmed vendor data contract — written reply dated 2026-10-13

The TickFlow technical support team **already confirmed in writing** the
key operational definitions for the user's Expert A-share use case.
These facts supersede our earlier assumption that all timestamp semantics
and a candle-close *rule* were completely undocumented:

- **K-line \`timestamp\` is BAR_END**, not BAR_START.
- The provider has **no separate \`is_final\` or \`closed\` field**.
- **Once a next K-line forms, the preceding K-line may be regarded as
  closed.** This is a provider-defined operational close, NOT an
  independently sealed/irreversible exchange record.
- Off-market, if a minute K-line receives **no volume update for more
  than one minute**, it can be regarded as no longer changing under
  ordinary delivery. This is *not* an immutable-data guarantee.
- 15m/60m timestamps normally advance monotonically; missing due labels
  should be checked on subsequent polling rather than invented.
- The provider may **revise K-line values about one hour after the
  close**. Post-close reconciliation and versioned audit are required;
  no source revision ID or guaranteed finality cutoff was supplied.
- Small JSON floating serialization mismatches can be validated with
  absolute bounds: \`max(open, close, low)-high <= 1e-5\` and
  \`low-min(open, close, high) <= 1e-5\`. Do not edit vendor prices.

This reply is stronger than the SDK's column schema alone. In particular,
the absence of an \`is_final\` field does **not** mean that *no* operational
closed-bar inference is possible. It means immutable provider/exchange
finality cannot be derived from that API alone.

\`audit_tickflow_vendor_successor_close()\` implements the conservative
version of this support rule on already-collected research snapshots.
For a target 15m ending at 09:45, it requires the *same provider's*
subsequent 10:00 bar to appear in the approved regular-session grid.
Because the research cache quarantines future-end-label forming candles,
this is slower than the provider's earliest "next candle formed" moment,
but remains strictly research-only. It emits
\`provider_operational_closed_research_only=true\`,
\`closure_rule=TICKFLOW_SUPPORT_2026_10_13_SUCCESSOR_KLINE\`,
\`bar_finality=NOT_VERIFIED\` and all trading/Radar gates BLOCKED.

The official reply distinguishes two separate notions of "closed":

| Evidence | Operational research closed? | Exchange/immutable finality? |
| --- | --- | --- |
| Boundary reached by wall clock | No | No |
| New same-provider K-line formed after the target | Yes, provider rule | No |
| 2 post-boundary snapshots and 5m→15m match | Integrity support only | No |
| 1h post-close correction window elapsed | Stronger settlement context | Still not guaranteed |
| Authenticated exchange/server-final revision seal | Not exposed by current SDK | Only if independently provided |

## Remaining P0: runtime qualification and amendment handling

**The vendor already answered BAR_END and operational close by successor.**
Remaining engineering questions are different:

1. **Upstream correction visibility:** How can later revisions after 15:00
   be linked to the source's revision/sequence? The provider warns of
   corrections around one hour after close but has not committed to a
   guaranteed immutable cutoff or issued a signed finality event.
2. **Production integration:** Apply the vendor operational-close rule to
   actual AWS read-only evidence without touching immutable finality flags
   or reopening SOURCE_ARBITER/RADAR/TRADE gates.
3. **Session + cross-period:** Verify the last due 1m/5m/15m/60m/1d
   grids, lunch break, exchange holidays and OHLCVA equality, not just
   one today's first 15m bar. Expert access includes 1m as confirmed
   in writing, but today's narrow research cache does not expose
   1m session_progress.
4. **Correction audit:** Carry out versioned post-close readbacks after
   the approximate revision window, compare full OHLCVA revisions,
   and preserve corrections rather than silently replacing provenance.
5. **Cloud version and rights:** Independently confirm AWS runtime/main
   SHA parity, SDK and transport rights, source freshness, reconnect
   consistency and authoritative account-level resource budget.

Vendor operational closure is appropriate for a strictly labeled
research signal. It is not the same as a permanently immutable record.
Current system admission gates remain **BLOCKED** until the reviewed
risk/admission policy and actual runtime qualification are completed.
