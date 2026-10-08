# TickFlow Isolated CN Qualification Probe V0.1

**State: research-only PREQUALIFICATION, not a production Provider.**

TickFlow is a candidate for the CN Cloud/Desktop Hot Path, not an authorized
canonical writer. Initial SDK code is sourced from the **official**
`tickflow-org/tickflow` Python repo (MIT license; PyPI module `tickflow`).
Review dependencies/network behavior before installing. Python >= 3.9.

Official documentation used for the probe:
- https://docs.tickflow.org/zh-Hans/sdk/python-quickstart
- https://github.com/tickflow-org/tickflow
- https://pypi.org/project/tickflow/

The official SDK uses `SYMBOL.SH` / `SYMBOL.SZ`, **not** `SH.SYMBOL`
or `SZ.SYMBOL`, and exposes:
`TickFlow.free()`, `TickFlow()`, `tf.quotes.get(symbols=[...])`,
`tf.klines.get(symbol,period=...,count=...)`,
`tf.depth.get(symbol)`, and
`tf.stream.subscribe("quotes", symbols)` /
`tf.stream.connect(block=False)` / `tf.stream.close()`.

## Tonight — staged isolated capability checks

Never paste an API key into GitHub, shell command arguments, printed stdout,
chat transcripts or repo files. The SDK reads `TICKFLOW_API_KEY` from its
runtime environment. Use a secret manager or user-scoped secure store outside
repo and do not assume entitlement until successful paid API queries.

Clean Windows environments require `tzdata`: Python's
`zoneinfo.ZoneInfo("Asia/Shanghai")` is evaluated when TickFlow is imported,
and `pip check` alone may miss this runtime dependency. A real Windows
isolation attempt reproduced `ZoneInfoNotFoundError`; installing
`tzdata==2026.3` into **that dedicated venv only** resolved it. The
reproducible dependency pins live at
`ops/requirements/tickflow-isolated-v0.1.txt`.

Create a dedicated **external** Python virtual environment; never install to
production Radar or AWS runtime before network/credential/licensing review.
Pin SDK to a reviewed exact version (`0.1.25`), not
`pip install --upgrade` and do not install unreviewed binaries.

Install from `ops/requirements/tickflow-isolated-v0.1.txt` into the
dedicated venv with `python -m pip install -r ...`; do not use global
Python's site-packages. Commands from repository root, with the
isolated environment activated:

```sh
python scripts/probe_tickflow_isolated.py --mode metadata
python scripts/probe_tickflow_isolated.py --mode free
# Only after official purchase and API key configured securely:
python scripts/probe_tickflow_isolated.py --mode premium
# Explicit low-volume WS smoke (bounded to 15s), post entitlement:
python scripts/probe_tickflow_isolated.py --mode premium --ws-seconds 10
```

Default watchlist is `159611.SZ 518880.SH 512730.SH`, never more than five
symbols in the initial probe. Paid REST smoke performs at most one small quote
batch, five short K-line requests for *one* symbol, and one L1 depth request;
optional WS subscribes to the small set in a short test. No automatic loops,
unbounded retry, subscriptions to whole market, trading or canonical writes.

Each operation reports only completed/failed/skipped, elapsed milliseconds,
row count when safe and exception **class only**. Never print market prices,
provider raw payload, HTTP URLs, response text or credentials. A working
REST endpoint does not prove timezone, units, adjustment, bar finality, market
event timestamps, source provenance, second source equivalence, or an SLA.

Key missing => premium probe `SKIPPED`; free daily service is not minute or
realtime qualification. Zero WS events after close is NOT proof of provider
failure, whereas nonzero events do NOT imply continuity or entitlements.

## Tomorrow — A-share session-specific qualification

At 09:30, 11:30, 13:00, 14:57-15:00 Shanghai time, capture bounded,
uniquely-timestamped source events through separate, monitored probes in
AWS Tokyo and desktop. **Only after user-provided official credentials, WS
entitlement and allowed cloud/overseas location have been verified.**

Verify 1m finality and timestamp semantics, 15/60m aggregation against the
session calendar, volume/amount units, price/OHLC/amount/volume versus
qualified Tencent/TDX/Eastmoney/GM where available, missing/out-of-order,
WS latency, reconnect time and dropped updates; measure P50/P95/P99 across
**unique messages**, not repeated reads.

Desktop+AWS same-account concurrency, WS account-wide versus per-connection
limits, overseas IP authorization and billing remain UNKNOWN until
official provider evidence and isolated experiments.

## Required architectural admission

Desktop TickFlow, Cloud TickFlow and existing Eastmoney/Tencent sources must
be separately qualified. Source Arbiter chooses the fastest **qualified**
single authoritative source per symbol/timeframe, records source, switch
reason, latency, freshness, health/sequence and cross-check discrepancies.
Provider events must never themselves grant Radar execution authorization.

`LIVE_TRADE=NO` · `RADAR_ADMISSION=BLOCKED` ·
`can_confirm_signal=false` · `SOURCE_ARBITER_ADMISSION=BLOCKED`.

No paid plan has been purchased by this engineering slice; the user's
separate TickFlow Expert purchase and credential setup are outside CI.

## Isolation findings on 2026-10-08 (JST)

On the user's authorized Windows desktop, a separate
`%LOCALAPPDATA%\\StockRazor\\IsolatedProbes\\tickflow\\venv`
has been created without modifying the global Python or trading installation.
The exact SDK `tickflow==0.1.25` plus `tzdata==2026.3` imports
successfully. `pip check` passes, but a new venv without tzdata failed at
`ZoneInfo("Asia/Shanghai")` despite `pip check` showing healthy, hence
the explicit Windows pin.

The SDK's free-mode announcement contains non-ASCII characters and can raise
`UnicodeEncodeError` on Windows consoles using incompatible code pages.
The probe now silences provider stdout/stderr into a UTF-8 null sink and
limits offline HTTP queries to an 8-second timeout and zero automatic
retries, while emitting only sanitized status/evidence metadata.

The local `TICKFLOW_API_KEY` environment variable was absent when checked.
This is **not** a purchase, login, WS, AWS or paid-data qualification result.
