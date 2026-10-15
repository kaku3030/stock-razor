# Windows ↔ AWS TickFlow minute-bar acceptance (research-only)

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
python scripts/audit_tickflow_windows_readonly.py --execute --timeframe 15m
python scripts/audit_tickflow_windows_readonly.py --execute --timeframe all
```

Without `--execute`, **zero** provider calls are made. The bounded actual
read uses exactly `159611.SZ` and `518880.SH`, at most two REST Kline calls
for each 15m, 60m and 1d timeframe (six total); `as_dataframe=False`,
`adjust=none`, `max_retries=0`, timeout 8s. It does **not** subscribe to
WS, place orders, publish canonical data, or write cache/account balances.

The output includes request milliseconds, bounded row counts, duplicate,
invalid and future/forming row counts, and the number of Shanghai exchange
session-grid due labels observed **after a 90-second publication grace**.
All D1 labels on the current Shanghai date are quarantined from proven
historical D1, even after 15:00 unless independent finality proof exists.
Never use this research output as a trade signal.

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
