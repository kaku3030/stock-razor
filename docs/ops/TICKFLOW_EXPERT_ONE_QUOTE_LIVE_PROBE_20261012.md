# TickFlow Expert one-quote A-share live session gate — 2026-10-12

The A-share public Eastmoney/Tencent observer is seeing new 2026-10-12
minute observations during the market session, but it does **not** prove the
separate TickFlow Expert source is streaming/reliable. Today's initial
cloud metadata, IAM role and free historical probes were successful;
the free historical endpoint cannot prove live quotes, and the Premium
contract remains explicitly unqualified.

The previous Expert Premium Probe can make 8+ REST calls (quote, five
minute-K periods, repeated 15m/60m per ETF and order-book depth) plus
optional WS, which is too broad for a minimal quota-aware validation.

This patch defaults the **existing** manually triggered Premium workflow
to `quote_only=true`. In that scope:
- Read-only, maximum **one** TickFlow `quotes.get` request for at most two
  A-share/ETF symbols (existing default 159611.SZ and 518880.SH).
- Official TickFlow SDK instantiated with `max_retries=0` and bounded
  timeout; **no** `klines.get`, `depth.get`, WebSocket connection,
  source arbitration, canonical ingestion or trading.
- `ws_seconds` MUST be `0` in quote-only mode. Previous broad diagnostics
  require an *explicit separate* `quote_only=false` selection.
- Only operation names, completed/failed states, total row counts and
  elapsed time may appear in the sanitized GitHub workflow result.
  Raw symbols, prices, provider keys, account data and payloads remain
  out of public Actions outputs.
- A green AWS run proves execution of the bounded request, **not** quote
  freshness, exchange-timestamp semantics, independent cross-source
  parity, provider entitlement, stable WebSocket service or Source
  Arbiter/Radar promotion.

Use the dedicated manually opt-in
`.github/workflows/probe-tickflow-aws-premium.yml` on exact main with
`enable_premium_probe=true`, `quote_only=true`,
`ws_seconds=0`, and the previously authorized AWS Secrets Manager
**reference**, not any raw key. Confirm subscription, account-level
quota sharing and request cost budget independently BEFORE dispatch.
Only one dispatch is intended; repeated attempts consume a shared quota.
Never store or paste the API key into GitHub comments or inputs.

**No actual premium provider request is executed by merging this PR.**
The current cloud A-share source remains
`EASTMONEY_PRIMARY_TENCENT_FALLBACK` with intraday currentness
UNPROVEN and Radar BLOCKED. The separate US OpenD cloud service is
already deployed at exact main and remains read-only.

Safety invariants: `PAPER_AUTO_READY=NO`,
`RADAR_ADMISSION=BLOCKED`,
`SOURCE_ARBITER_ADMISSION=BLOCKED`,
`LIVE_TRADE=NO`.
