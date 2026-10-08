# CN Cloud Gold ETF Watchlist Alignment V0.1

Status: read-only cloud observation extension; **not** market data currentness
qualification or Radar admission.

The AWS CN observer previously configured three symbols by default:
`512730,159611,159363`. The US/CN benchmark included `518880`, which was
**not** in that collector watchlist. A missing CN reader payload for that ETF
therefore cannot be interpreted as measured 0ms provider or canonical latency.

This slice adds `518880` as a fourth bounded read-only ETF symbol.
The same observer already fetches 15m, 60m and 1d market observations with
Eastmoney first and Tencent fallback under existing safety controls.

Operational impact: one additional symbol, up to three additional timeframes
per polling cycle. This increases external HTTP load and must be verified
against provider limits and AWS runtime health after deployment. No paid
provider, no automated trading and no relaxed data-quality gate.

The source retains fail-closed intraday timestamp/currentness semantics.
An unclosed 15m bar, missing bar, stale provider, inconsistent time index,
or unknown entitlement cannot become confirmed Radar evidence.

`RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`,
`can_confirm_signal=false`; qualification remains separate.

Acceptance path: fresh CI, exact-head merge, deploy, SSM audit, verify the
new symbol exists and only then rerun cloud read benchmarks.
