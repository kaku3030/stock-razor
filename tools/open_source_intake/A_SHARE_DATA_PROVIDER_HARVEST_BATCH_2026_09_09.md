# Open-Source Intake — A-Share Data Provider Harvest Batch 2026-09-09

Status: RESEARCH / PROVIDER-SCREENING LEDGER. Non-production.

## Goal

Ensure A-share market-data interfaces are treated as a first-class Foundation/Data Reliability lane rather than an afterthought to the US/Futu work.

This batch screens open-source/client-layer candidates against Radar's existing Data Source Registry principle:

> accuracy > timeliness > traceability > stability > cost > ease of integration

No provider in this file is approved as CORE. Provider maturity, stars, or wide coverage never bypass endpoint-level semantic tests, reconciliation, Data Health, failure injection, or Shadow validation.

## Current repository gap

Default-branch code search on `kaku3030/stock-razor` did not find obvious `akshare`, `baostock`, `mootdx`, `pytdx`, or `tushare` integration references at this screening point.

Interpretation:

- do not assume A-share provider integration already exists merely because A-share research features exist elsewhere in the project;
- the provider boundary should remain explicit and provider-neutral;
- future implementation must enter through the existing MarketData/Data Health architecture, not directly from strategy/screening code.

## Candidate: akfamily/akshare

- URL: https://github.com/akfamily/akshare
- License: MIT.
- GitHub activity observed 2026-09-09: repository active; pushed in 2026; ~22.5k stars at screening time.
- Scope: very broad financial-data interface library, including many A-share realtime/history/fundamental/board/flow endpoints.

### Useful evidence

Current source includes `stock_zh_a_spot_em()` labeled as Shanghai/Shenzhen/Beijing A-share realtime quotes and calls an Eastmoney `push2` HTTP endpoint. The same project exposes multiple A-share spot/history interfaces from different upstream websites.

This breadth is valuable but also means AKShare is a **multi-upstream adapter collection**, not one authoritative provider with one stable semantic contract.

### Risks / Defect Audit focus

1. Endpoint stability is upstream-specific. AKShare changelog history contains repeated fixes to A-share spot/history interfaces, so package-level health cannot substitute for endpoint-level contract tests.
2. Numeric coercion in adapter code may convert upstream malformed values to NaN; Radar must still preserve its own malformed-vs-missing semantics and Data Health evidence.
3. Public website endpoints can change fields, anti-bot behavior, hostnames, rate limits, or response shapes without a formal provider SLA.
4. `realtime` naming does not prove source timestamp freshness, exchange-origin latency, or Currentness/Continuity semantics.
5. Different AKShare endpoints may ultimately depend on Eastmoney/Sina/Tencent/THS and therefore are not necessarily independent reconciliation sources.

### Radar disposition

`ADAPT / RESEARCH-ENRICHMENT / FALLBACK-CANDIDATE`.

Recommended uses first:

- sector/industry/concept metadata;
- breadth/market-wide snapshots;
- research enrichment and non-critical fundamental/flow datasets;
- cross-check/fallback endpoints after dependency-lineage mapping.

Do **not** make an AKShare web-scraped endpoint the sole production LIVE/currentness authority without live endpoint characterization and a provider-specific contract.

Promotion: `EXTERNAL CANDIDATE`.

## Candidate: mootdx/mootdx

- URL: https://github.com/mootdx/mootdx
- License: MIT.
- GitHub metadata at screening: ~2.25k stars; repository not archived; last repository push observed 2024-07-16.
- Scope: convenience layer around TDX protocol clients.

### Useful evidence from current source

`StdQuotes` exposes:

- realtime security quotes;
- security/index bars;
- realtime minute data;
- historical minute data;
- transaction/tick data;
- stock lists;
- corporate/finance/xdxr information.

It has explicit socket/client timeout configuration and reconnect/auto-retry-related mechanics inherited from the underlying TDX client.

### Risks / Defect Audit focus

1. Maintenance freshness is weaker than AKShare based on current push history.
2. Server selection/best-IP and TDX public-server availability are operational dependencies outside Radar control.
3. Auto-retry/reconnect must not silently become Radar Data Health or Currentness proof.
4. Historical helper code includes heuristic non-trading-day approximations in at least one path; such convenience logic is unacceptable as authoritative calendar/history-range semantics for Radar without replacement/audit.
5. TDX field/timestamp semantics and server differences require empirical characterization.
6. A reconnecting client can return data after a transport break; this must still pass Radar currentness/continuity/reconciliation gates.

### Radar disposition

`ADAPT / TEST-REUSE / TDX-FALLBACK-CANDIDATE`.

Recommended first role:

- auxiliary intraday/quote source;
- TDX failover/fallback lane;
- independent comparison against HTTP/web-scraped sources when lineage is genuinely different;
- provider-semantics experiments.

Not approved as the sole primary historical or LIVE source.

Promotion: `EXTERNAL CANDIDATE`.

## Candidate: BaoStock / baostock ecosystem

Screened GitHub repository: https://github.com/shimencaiji/baostock

- repository not archived but last push observed in 2019;
- GitHub metadata did not identify a license for this repository;
- repository contains scripts around BaoStock history, financial statements, corporate actions and related datasets.

### Radar value

BaoStock remains useful conceptually for:

- historical bars;
- corporate-action/adjustment cross-checks;
- financial statement/backfill datasets;
- offline reconciliation and repair.

### Risks

- the screened GitHub repository itself is not a sufficiently current or license-clean basis for direct source adoption;
- realtime/live suitability should not be inferred;
- actual package/service availability, update cadence, historical corrections and adjustment semantics require live empirical checks against the currently distributed BaoStock service/package rather than this old repository alone.

### Radar disposition

`HISTORICAL / BACKFILL / RECONCILIATION CANDIDATE`.

Do not promote from this GitHub repository alone. Treat current service/package behavior as a separate provider-semantics validation task.

Promotion: `EXTERNAL CANDIDATE` only.

## Candidate: waditu/tushare

- URL: https://github.com/waditu/tushare
- License: BSD-3-Clause.
- ~15.4k stars at screening time; GitHub main repository last push observed 2024-03-13.
- Pro client is token-authenticated HTTP and includes a finite request timeout.

### Radar value

Potentially high value for structured A-share datasets such as:

- daily/history/fundamental/reference datasets;
- trading calendar/reference data;
- corporate actions and financial datasets;
- datasets difficult to reconstruct reliably from public webpage scraping.

### Risks / gating questions

1. Current Pro API permissions/point requirements and cost vary by endpoint and must be inventoried.
2. Request-frequency/rate limits must be represented as capability metadata, not discovered only through runtime errors.
3. Data availability delay must be measured endpoint by endpoint.
4. Token-authenticated API success does not prove field/currentness quality.
5. The GitHub client repository's update cadence is not equivalent to backend service freshness.

### Radar disposition

`ADAPT / STRUCTURED-HISTORY-REFERENCE CANDIDATE`.

Strong candidate for selected authoritative structured datasets if endpoint availability/cost/timeliness pass empirical capability tests; not assumed to be the best intraday realtime feed.

Promotion: `EXTERNAL CANDIDATE`.

## Candidate: rainx/pytdx

- URL: https://github.com/rainx/pytdx
- Python TDX interface.
- Repository is archived; default branch is `archive`; last push observed 2020-04-15.

### Radar disposition

`REJECT DIRECT PRODUCTION DEPENDENCY / METHOD-PROTOCOL HARVEST ONLY`.

Useful only for:

- historical protocol knowledge;
- old fixtures/failure cases;
- comparison when auditing newer TDX implementations.

For new production work, prefer a maintained successor/wrapper after independent audit.

## Initial provider-role matrix

| Capability | Preferred screening lane | Secondary / comparison lane | Notes |
|---|---|---|---|
| Intraday quote / minute / bars | TDX-family candidate such as mootdx + separately validated source | AKShare spot endpoints | Must prove timestamp/currentness; no `realtime` label trust |
| Broad market snapshot / boards / concepts | AKShare | TDX where available | Good research/discovery value; map upstream lineage |
| Historical OHLC backfill | TuShare/BaoStock candidates | TDX/AKShare cross-check | Adjustment, calendar and correction semantics must be normalized |
| Corporate actions / fundamentals | TuShare/BaoStock + selected AKShare endpoints | cross-provider reconciliation | point-in-time / announcement-time rules required for Strategy Lab |
| Trading calendar | Prefer explicit structured authoritative/reference source after validation | exchange/provider cross-check | Never use weekday/holiday heuristics |
| Realtime fallback | TDX-family | independent HTTP/API lane | Health degradation/failover must be explicit |

This table is a screening hypothesis, not final provider priority.

## A-share Provider Contract requirements

Any A-share source promoted into Radar must declare at least:

- `provider_id` and upstream lineage;
- market coverage: SH/SZ/BJ/ETF/index/etc.;
- data capability: quote/bar/tick/fundamental/calendar/flow/etc.;
- realtime vs delayed vs end-of-day availability;
- source timestamp semantics and timezone;
- bar interval boundary semantics;
- adjustment mode and corporate-action semantics;
- trading-session/lunch-break behavior;
- auction/pre-open/closing-auction coverage where relevant;
- suspension/no-trade semantics;
- request/rate-limit policy;
- finite timeout/retry policy;
- missing/malformed-data behavior;
- provider corrections/revisions if known;
- provenance/lineage sufficient to know whether two apparent providers are actually the same upstream;
- entitlement/cost requirements;
- historical earliest/latest coverage;
- currentness proof capability;
- fallback/reconciliation role.

Unknown fields remain UNKNOWN; adapters must not invent semantics.

## Required empirical acceptance pack before CORE use

For each selected provider/capability:

1. same-symbol/same-timeframe comparison across at least two genuinely independent sources;
2. open/midday break/afternoon/close session boundary samples;
3. suspended stock / zero-trade interval case;
4. ETF + ordinary stock + index coverage where claimed;
5. ex-rights/dividend/adjusted historical case;
6. malformed/empty/timeout/network-failure behavior;
7. rate-limit behavior;
8. timestamp timezone and interval-boundary proof;
9. currentness and stale-data negative tests;
10. retry/fallback must not silently preserve old healthy state;
11. T+1 reconciliation report and correction detection;
12. historical sample cross-check against a trusted third source when possible.

## Current recommendation

Do not choose one universal A-share provider.

Preferred architecture remains **capability-specific multi-source routing**:

```text
A-share Capability Registry
    |
    +-- realtime/intraday provider lane
    +-- historical/backfill provider lane
    +-- fundamentals/corporate-action lane
    +-- calendar/reference lane
    +-- research-enrichment lane
    |
    v
normalization -> Data Health -> reconciliation -> downstream Radar
```

The Data Source Registry should rank providers **per capability**, not with one global winner.

## Near-term work order

P0/P1:

1. create A-share capability inventory matching Radar's actual needs: daily / 1H / 15m / market snapshot / ETF / sector / calendar / corporate actions;
2. run live empirical probes for AKShare Eastmoney spot/history and mootdx TDX intraday paths;
3. characterize timestamp/bar-boundary/lunch-break/suspension semantics;
4. verify TuShare/BaoStock current availability and permissions for historical/calendar/corporate-action datasets;
5. build a provider-lineage map so Eastmoney via AKShare is not mistakenly treated as independent from another Eastmoney adapter;
6. produce cross-provider reconciliation fixtures before implementing automatic failover.

No provider is promoted to CORE by this document.

## Cross-window synchronization rule

This file is the durable synchronization surface for A-share provider work. Any other development/chat window working on Stock Razor should read this file and the main Harvest Ledger rather than relying on conversational memory.

## Governing rule

> A provider is not good or bad globally; it is trustworthy only for a proven capability under proven semantics.
