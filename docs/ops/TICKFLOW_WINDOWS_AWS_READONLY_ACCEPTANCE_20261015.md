# Windows ↔ AWS TickFlow minute-bar acceptance (research-only)

> Hybrid V1.0 update: Windows TickFlow local acceptance follows [the current local procedure](TICKFLOW_WINDOWS_LOCAL_ACCEPTANCE.md). AWS TickFlow pairing is no longer a requirement. The older evidence below retains its original scope.

A Windows desktop and the AWS Tokyo collector are **independent** TickFlow
observation locations. A green GitHub Action, healthy heartbeat, or a regular
session-grid label is **not** evidence of exchange-finalized 15m/60m candles.

## Windows opt-in replay

Requires official Python `tickflow==0.1.25`, `pywin32`, timezone data, and
an *existing* Windows Credential Manager generic credential target
`StockRazor/TickFlow/APIKey`. Never place the key in a script, CLI parameter,
GitHub repository, shell history, screenshot or console output.

Run explicitly from the local repository:

```powershell
python scripts/audit_tickflow_windows_readonly.py
python scripts/audit_tickflow_windows_readonly.py --execute --timeframe 5m
python scripts/audit_tickflow_windows_readonly.py --execute --timeframe 5m --research-exit
python scripts/audit_tickflow_windows_readonly.py --execute --timeframe 15m
python scripts/audit_tickflow_windows_readonly.py --execute --timeframe all
```

Without `--execute`, **zero** provider calls are made. The bounded actual
read uses exactly `159611.SZ` and `518880.SH`, at most two REST Kline calls
for each 5m, 15m, 60m and 1d timeframe (eight total); `as_dataframe=False`,
`adjust=none`, `max_retries=0`, timeout 8s. It does **not** subscribe to
WS, place orders, publish canonical data, or write cache/account balances.

The output includes request milliseconds, bounded row counts, duplicate,
invalid and future/forming row counts, and the number of Shanghai exchange
session-grid due labels observed **after a 90-second publication grace**.
The 5m route has TWO independent results: strict valid OHLC coverage and
non-mutating TickFlow vendor-float research-only coverage (<=1e-5,
ETF tick-grid valid). The latter never asserts exchange finality or
source/Radar admission.
All D1 labels on the current Shanghai date are quarantined from proven
historical D1, even after 15:00 unless independent finality proof exists.
Never use this research output as a trade signal.

## 2026-10-15 10:18 CST exact-code root cause isolated

Additional physical Windows probe executed the **exact cloud protected-main**
`data_provider/cn_tickflow_research_cache.normalize_bars` source blob
`d11076c4989277413a366f308e1bd4c7274246f3` without changing its
normalization rules, on the official `TickFlow==0.1.25` compact response
(`15m`, `count=96`, `adjust=none`, zero SDK retries).

For `159611.SZ`, 96 SDK rows produced only **94 retained**: one
`TODAY_FUTURE_LABEL` and one `TODAY_LOW_ABOVE_BODY`. The one malformed
row lies at the **second** due 15m ordinal (10:00 CST); a bounded vendor
precision diagnostic classified it `GAP_LT_1BP`,
`ETF_TICK_LATTICE_NEAR`, and
`ETF_LATTICE_QUANTIZE_WOULD_ENCLOSE_BODY`.
There were **no credentials or OHLC prices** in diagnostics.
`518880.SH` had 95 retained from 96, with only one forming future label.

**Root cause clarified:** the earlier desktop PASS was obtained with a
`<=0.00001` OHLC *tolerance*, while the cloud intraday gate rejects
non-strict OHLC even for a tiny positive low-vs-close drift. This can
fully reproduce the reported 159611 `BAR_LABEL_BEHIND_SESSION` on
Windows using the cloud's exact normalizer; a regional data discrepancy is
therefore **not established**. A different AWS vendor response is still
possible, but is no longer required to explain the symptom.

The Windows audit now distinguishes a returned grid label from a **strictly
valid OHLC** grid label, marking the tiny precision anomaly as a missing
strict qualified due boundary, not an apparently perfect PASS. Do not
automatically round/fix provider price fields, suppress strict research
guards, promote Radar, or claim source finality. Await independently
approved vendor precision policy and cloud/auditor rollout.

## Cloud evidence and discrepancy

Use the *existing* protected-main, owner-only read-only workflow
`Audit TickFlow AWS Research Feed and MCP (Read Only)` with exact PR #658
comment `/stock-razor tickflow-audit read-only`.
The workflow audits a fixed EC2 instance, takes two private-cache/MCP
snapshots 65 seconds apart, and exports only allowlisted enums, row-count
buckets, sequence/age and finality-gate states.

On 2026-10-15 10:01–10:07 Asia/Shanghai, Windows returned both 09:45 and
10:00 15m labels for **both** ETFs, including `159611.SZ` at count 96
and no SDK retries. AWS successive isolated SSM audits
`38668797244` and `38669105484` still rejected `159611.SZ`
15m as `BAR_LABEL_BEHIND_SESSION`; `518880.SH` passed the same
boundary. This is an actual desktop/cloud disagreement, **not fully
qualified live data**, and the cause has **not** been proven.

The publisher/source-audit PR #754 adds due-grid continuity checks and safe
diagnostics, but CI PASS before a reviewed deployment does not qualify
the cloud. Do **not** alias an Eastmoney/Tencent fallback to TickFlow,
silently promote `BAR_LABEL_BEHIND_SESSION`, or equate `PASS_RESEARCH_ONLY`
with exchange bar finality.

**Acceptance gates**: desktop and cloud both have consecutive due 15m labels,
cloud 60m first 10:30 boundary after 90s; sequence/heartbeats advance,
MCP source identity matches, provider timestamp/currentness and cross-provider
same-session parity independently reviewed. No live trading/auto Paper:
`RADAR_ADMISSION=BLOCKED`, `SOURCE_ARBITER_ADMISSION=BLOCKED`,
`PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO`, `TRADE_EXECUTION=NO`.

The explicit `--research-exit` flag only changes CLI **exit status** for a full
bounded research grid; it never changes `status=BLOCKED_UNVERIFIED` for non-strict
OHLC, never bypasses invalid/large-gap/missing-grid evidence and never turns the
research tool into a trading source. Without that flag, strict validation
continues to fail closed when current-day vendor float rows are present.
