# A-Share Intraday 15m / 1H Capability Truth — 2026-09-09

Status: Harvest evidence / capability audit. No provider routing, Currentness, strategy, AI, or trading behavior changes.

## Governing distinction

This audit keeps three facts separate:

1. **External/provider capability** — an upstream library/service/protocol can request a 15m/60m bar.
2. **Radar implemented capability** — Stock Razor currently exposes and normalizes that interval through an admitted adapter/capability contract.
3. **Currentness authority** — the provider semantics are sufficiently known to decide which bar should exist now and whether the newest bar is current/complete.

These facts are not interchangeable.

> `EXTERNAL_CAPABLE != RADAR_IMPLEMENTED != CURRENTNESS_VERIFIED`

The current `DataCapabilityService` declares only coarse A-share capabilities such as `quote.realtime`, `kline.daily`, `index.daily`, `market.overview`, and `financial.snapshot`; it does not currently declare `kline.15m` or `kline.1h` for the CN providers audited here.

## Status vocabulary

- `RADAR_IMPLEMENTED` — current admitted Stock Razor adapter exposes the interval.
- `EXTERNAL_CAPABLE_NOT_ADAPTED` — external library/service exposes it; current Radar adapter does not.
- `PROTOCOL_CAPABLE_NOT_ADAPTED` — underlying wire/protocol supports it; current Radar adapter does not.
- `HISTORICAL_INTRADAY_CANDIDATE` — useful for backfill/reconciliation/replay, not a realtime Currentness primary.
- `ENTITLEMENT_REQUIRED` — capability exists only with explicit external permission/package/token rights.
- `UNKNOWN` — evidence is insufficient; do not assume capability.

## Current truth table

| Provider / route | Radar 15m | Radar 1H | External/provider evidence | Access / lineage | Timestamp & session semantics | Currentness suitability | Harvest disposition |
|---|---|---|---|---|---|---|---|
| **EfinanceFetcher** | NOT IMPLEMENTED | NOT IMPLEMENTED | efinance `stock.get_quote_history(..., klt=15/60)` supports 15m/60m in upstream library; current Radar code hardcodes `klt=101` daily for stock and ETF history | Free wrapper; upstream lineage = **Eastmoney** | Intraday bar timestamp boundary/completion semantics not yet frozen; shares Eastmoney family with AkShare EM | **NOT CURRENTNESS-VERIFIED** | `EXTERNAL_CAPABLE_NOT_ADAPTED`; do not count independently from AkShare EM reconciliation evidence |
| **AkshareFetcher / Eastmoney intraday candidate** | NOT IMPLEMENTED | NOT IMPLEMENTED | AKShare exposes A-share/ETF minute-history interfaces with 15/60 minute periods; current Radar `AkshareFetcher` uses daily history paths | Free wrapper; Eastmoney minute endpoint lineage; adapter identity != upstream independence | Intraday timestamp/completion/session-silence semantics still require evidence; adjustment behavior must be endpoint-specific | **NOT CURRENTNESS-VERIFIED** | `EXTERNAL_CAPABLE_NOT_ADAPTED`; candidate for bounded adapter slice after semantics/contract review |
| **PytdxFetcher** | NOT IMPLEMENTED | NOT IMPLEMENTED | Current source comment documents TDX `get_security_bars`: category 1=15m, 3=1h; actual `_fetch_raw_data()` hardcodes category 9 daily | TDX protocol; current dependency is archived `pytdx`; mootdx is a maintained-ish wrapper candidate, not approved dependency | Need provider/TDX timestamp boundary, lunch-break, current-forming-bar and reconnect semantics; current fetcher uses synchronous calls and wall-clock cooldown | **NOT CURRENTNESS-VERIFIED** | `PROTOCOL_CAPABLE_NOT_ADAPTED`; strong fallback/reconciliation candidate, not automatic primary |
| **mootdx candidate** | NOT IN RADAR | NOT IN RADAR | `Quotes.bars()` supports frequency 1=15m and 3=1h in public docs/source conventions | MIT wrapper over TDX; external candidate only | Semantics/failure/blocking/offset window need controlled audit; online bars are latest-offset oriented rather than current Radar date-range contract | **UNKNOWN for Currentness** | `EXTERNAL CANDIDATE / ADAPT-OR-TEST-REUSE`; no dependency approval yet |
| **TushareFetcher** | NOT IMPLEMENTED | NOT IMPLEMENTED | Official `rt_min` supports A-share `15MIN`/`60MIN`; `rt_min_daily` supports current-day minute replay; ETF `etf_mins` supports historical 15min/60min; index minute endpoints also exist | Service/token route; **minute entitlement is explicit/separate**; upstream lineage = Tushare | Official fields expose `time`/`trade_time`, but Currentness boundary/forming-row semantics still need provider evidence; permission/rate-limit behavior must be capability metadata | POTENTIALLY USEFUL REALTIME, **NOT YET CURRENTNESS-VERIFIED** | `EXTERNAL_CAPABLE_NOT_ADAPTED + ENTITLEMENT_REQUIRED`; promising independent lineage for reconciliation |
| **TickFlowFetcher** | NOT IMPLEMENTED | NOT IMPLEMENTED | Current Radar adapter explicitly requests `period="1d"`; no sufficiently authoritative external 15m/1h evidence captured in this audit | API-key/permission route; independent TickFlow lineage | Intraday external semantics remain UNKNOWN | **UNKNOWN** | Keep `CURRENT_RADAR_DAILY_ONLY / EXTERNAL_INTRADAY_UNKNOWN` until provider docs/runtime evidence closes it |
| **BaostockFetcher** | NOT IMPLEMENTED | NOT IMPLEMENTED | BaoStock ecosystem/API documentation supports `frequency="15"` and `"60"`; current Radar adapter hardcodes `frequency="d"` | Free/login API; separate lineage | Minute data is historical/delayed rather than live-current; exact provider timestamp semantics still need audit; indices do not share the same minute support | **NOT REALTIME CURRENTNESS PRIMARY** | `HISTORICAL_INTRADAY_CANDIDATE`; useful for backfill/cross-check/OOS, not live authority |

## Radar implementation evidence

### DataCapabilityService

Current `src/services/data_capability_service.py` definitions expose:

- Efinance: `quote.realtime`, `kline.daily`, `market.overview` for CN;
- AkShare: `quote.realtime`, `kline.daily`, `index.daily`, `market.overview`, `financial.snapshot` for CN (plus HK subsets);
- PyTDX: `kline.daily` CN;
- BaoStock: `kline.daily` CN;
- Tushare: `quote.realtime`, `kline.daily`, `market.overview` CN;
- TickFlow: `quote.realtime`, `kline.daily`, `index.daily`, `market.overview` CN.

There is no admitted `kline.15m` / `kline.1h` capability in this current service surface.

### PyTDX

`data_provider/pytdx_fetcher.py` explicitly records the protocol categories in comments:

- `0` = 5m
- `1` = 15m
- `2` = 30m
- `3` = 1h
- `9` = daily

But the current production fetch path calls `get_security_bars(category=9, ...)`. Therefore the only current Radar K-line capability exposed by that adapter is daily.

### Efinance

Upstream efinance `get_quote_history()` accepts `klt=15` and `klt=60`. Current Stock Razor `EfinanceFetcher`, however, explicitly calls `klt=101` for stock/ETF historical K-lines. The current adapter therefore remains daily-only.

Lineage warning: Efinance and AkShare Eastmoney routes must not be counted as independent upstream evidence merely because they are different Python adapters.

### AkShare

Current Stock Razor `AkshareFetcher` calls daily interfaces (`stock_zh_a_hist(... period="daily")`, ETF daily history, etc.). External AKShare exposes Eastmoney minute-history functions, but those are not admitted through the current Radar adapter/capability service.

### Tushare

Current `TushareFetcher` is not an admitted 15m/1H K-line adapter. Official Tushare service documentation nevertheless exposes dedicated minute capabilities including:

- A-share realtime minute `rt_min`: `1MIN/5MIN/15MIN/30MIN/60MIN`;
- A-share current-day minute replay `rt_min_daily`;
- ETF historical minute `etf_mins`: `1min/5min/15min/30min/60min`;
- ETF realtime minute routes;
- index minute routes.

These APIs carry explicit permission/entitlement rules. `TUSHARE_TOKEN configured` must never be treated as equivalent to `minute capability entitled`.

### TickFlow

Current `TickFlowFetcher._fetch_raw_data()` requests `client.klines.get(... period="1d", ...)`. No 15m/1H Radar capability follows from the presence of a generic `klines` client. External intraday capability remains UNKNOWN until authoritative provider evidence is harvested.

### BaoStock

Current `BaostockFetcher` hardcodes `frequency="d"`. External BaoStock API documentation supports 5/15/30/60 minute stock history, but available evidence describes minute data as delayed/historical rather than a live Currentness source. Treat it as backfill/reconciliation research candidate.

## Required capability contract before any adapter promotion

A future `kline.15m` / `kline.1h` provider capability must not be admitted using only a method name and frequency parameter. Minimum contract fields should include:

1. `provider_id` / adapter identity;
2. `upstream_lineage_id`;
3. instrument coverage: stock / ETF / index;
4. interval: 15m / 1h;
5. access mode: realtime push / realtime request / current-day replay / historical;
6. entitlement requirement and runtime capability probe;
7. source timestamp field and timezone;
8. source timestamp semantic: start/end/other/UNKNOWN;
9. forming-bar inclusion semantics;
10. exchange lunch-break/session alignment;
11. suspension / zero-trade / expected-silence semantics;
12. adjustment mode and whether OHLC/volume are adjusted;
13. volume unit and amount unit;
14. maximum lookback / pagination / per-call row limits;
15. provider-side publication delay / update cadence if authoritative evidence exists;
16. blocking/timeout behavior;
17. malformed vs missing field behavior;
18. Currentness eligibility: `ELIGIBLE / DIAGNOSTIC_ONLY / HISTORICAL_ONLY / UNKNOWN`.

## Acceptance / evidence pack for A-share 15m/1H

Before a provider becomes a Currentness authority, collect provider-scoped evidence for at least:

- normal morning session transition;
- 11:30 lunch break and 13:00 reopen;
- 15:00 close and final-bar identity;
- current forming bar vs completed bar behavior;
- suspended/zero-trade instrument behavior;
- source timestamp timezone and boundary meaning;
- stock + ETF, where provider claims both;
- adjustment and volume-unit reconciliation;
- one controlled cross-provider same-symbol comparison using **independent upstream lineage**, not wrappers over the same backend;
- blocking/failure/empty/malformed response behavior.

## Architecture implication

Do **not** build a new parallel A-share Currentness engine inside each fetcher. The target should be:

`provider-specific semantic evidence -> normalized intraday capability contract -> shared Data Health / Currentness authority`

PR #40 A0.1/A0.2 already supplies the upstream-lineage substrate needed to prevent false independence in reconciliation. Reuse it rather than inventing a second identity model.

## Recommended provider roles at this stage

- **Tushare:** strongest candidate for an independent entitlement-backed realtime 15m/1H evidence lane; adapt only after entitlement + timestamp/forming semantics are explicit.
- **TDX / PyTDX / mootdx:** strong independent fallback/reconciliation candidate; harvest semantics and blocking behavior before adapter promotion.
- **AKShare / Efinance Eastmoney:** useful accessible intraday candidates, but one upstream lineage family for independence counting.
- **BaoStock:** historical/backfill/cross-check candidate, not live Currentness primary.
- **TickFlow:** keep open as a potentially useful independent source; external intraday capability remains UNKNOWN in this audit rather than guessed.

## External evidence references reviewed

- efinance upstream source/docs: `get_quote_history(..., klt=1/5/15/30/60/101/...)` and Eastmoney K-line endpoint.
- Tushare official docs: `rt_min`, `rt_min_daily`, `etf_mins`, ETF realtime minute and index minute interfaces, with explicit minute permissions.
- mootdx public repo/docs: `Quotes.bars()` frequency mappings include 15m and 1H.
- BaoStock API/ecosystem documentation: `query_history_k_data_plus` supports 5/15/30/60 minute stock history; minute data is suitable for historical research rather than assumed realtime authority.

## Harvest status

This document is **CAPABILITY TRUTH / GAP ANALYSIS**, not implementation authorization.

No provider is promoted to `kline.15m`/`kline.1h` Radar capability by this audit alone. No Currentness threshold, fallback order, provider score, or SHADOW/CORE decision is introduced.
