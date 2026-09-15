# A-Share Upstream Provider Migration Matrix — 2026-09-09

Status: HARVEST / GAP ANALYSIS. Non-production.

Upstream audited at exact main SHA:

`ZhuLinsen/daily_stock_analysis@089d9d26d68f8b839ea5a74a3784e4402925f8b7`

Purpose: determine what Stock Razor should reuse from its upstream A-share data stack, what must be repaired before adaptation, and what should not be imported.

This document is a cross-window synchronization artifact. Other Stock Razor workstreams should use this matrix together with `A_SHARE_DATA_PROVIDER_HARVEST_BATCH_2026_09_09.md` instead of reconstructing the conclusions from chat history.

## 1. Major discovery

The upstream project already contains a mature multi-source market-data architecture. It is not necessary to build an A-share provider framework from zero.

Observed upstream components include:

- `DataFetcherManager` / `BaseFetcher` strategy boundary;
- Efinance;
- AkShare;
- Tushare;
- TickFlow;
- Pytdx;
- Baostock;
- Tencent direct fallback;
- unified realtime quote model;
- source priority configuration;
- circuit breakers/cooldown;
- source/fallback metadata;
- provider capability overview;
- fixed index-specific routes;
- tests for routing/fallback/provider capabilities.

The correct Harvest action is therefore **selective adaptation**, not rewrite.

## 2. DIRECT-ADAPT candidates

These are high-value patterns whose semantics are broadly compatible with Radar after normal repository integration review.

### 2.1 Provider strategy boundary

Harvest:

- common fetcher interface;
- manager/orchestrator boundary;
- normalized market-symbol routing;
- capability-specific handler presence checks;
- provider failures isolated from downstream strategy code.

Radar modification:

- provider ranking must be capability-specific rather than one global provider winner;
- provider execution remains subordinate to Data Health and provenance.

Disposition: `ADAPT`.

### 2.2 Provider capability overview

Upstream `DataCapabilityService` already follows several Radar-compatible disciplines:

- configured/enabled/unknown/degraded distinctions;
- dataset/market capability mapping;
- no Cartesian-product inference from provider-level market/dataset lists;
- unprobed sources may stay UNKNOWN rather than being declared healthy;
- current runtime route availability can affect reported capability.

Disposition: `ADAPT / TEST-REUSE`.

This is preferable to inventing a second capability registry.

### 2.3 Realtime source/fallback provenance fields

Useful fields in upstream `UnifiedRealtimeQuote`:

- `source`;
- `fetched_at`;
- `provider_timestamp`;
- `fallback_from`;
- market/currency metadata;
- missing-field/data-quality metadata.

Disposition: `ADAPT` the provenance shape, but **do not import upstream stale/currentness authority unchanged**.

### 2.4 Scenario-specific routes

Upstream already avoids one universal route in several areas:

- normal A-share daily route;
- registered A-share index route;
- realtime route;
- market-review route;
- screening snapshot route.

This confirms the Radar decision that provider order should be capability/scenario specific.

Disposition: `ADAPT / TEST-REUSE`.

### 2.5 Routing/fallback tests

High-value upstream test families include:

- A-share index routing;
- realtime source routing;
- TickFlow manager routing;
- fallback logging;
- data capability service;
- symbol-market routing.

Disposition: `TEST-REUSE`, rewritten against Radar frozen invariants where necessary.

## 3. ADAPT-AFTER-REPAIR candidates

### 3.1 Numeric normalization

Upstream `safe_float()` treats examples such as:

- blank;
- `-`;
- `--`;
- NaN;
- arbitrary conversion failures

as the same `None`-like outcome.

This conflicts with Radar Foundation Data Reliability R1, where malformed non-empty provider evidence must remain distinguishable from genuine missing evidence and become explicit quality evidence such as `INVALID_NUMERIC`.

Required repair:

```text
missing evidence != malformed evidence != valid numeric evidence
```

Disposition: `ADAPT AFTER REPAIR`.

Do not copy `safe_float` semantics as authoritative normalization.

### 3.2 Realtime stale/currentness logic

Upstream manager currently derives diagnostic stale state from roughly:

```text
stale_seconds = fetched_at - provider_timestamp
is_stale = stale_seconds > realtime_cache_ttl
```

with a default fallback TTL of 600 seconds when no explicit TTL is supplied.

This is useful as **age telemetry** but conflicts with Radar's frozen Currentness model if treated as market-currentness authority.

Reasons:

- lunch break / expected silence;
- suspension / no-trade intervals;
- pre-open / close boundaries;
- provider timestamp semantics may differ;
- historical/current endpoints are not equivalent;
- age alone does not prove ordered provider progress.

Required repair:

- retain `fetched_at`, provider timestamp and age as evidence;
- move Currentness authority to Data Health / provider semantic progress rules;
- keep UNKNOWN/UNVERIFIED when progress cannot be proven;
- do not let `is_stale=False` imply LIVE/current.

Disposition: `ADAPT TELEMETRY / REJECT AUTHORITY`.

### 3.3 Circuit-breaker elapsed clock

Upstream circuit-breaker/cooldown logic uses `time.time()` for elapsed availability decisions in observed paths.

Radar rule:

- UTC/wall clock for audit timestamps;
- monotonic time for elapsed timeout/cooldown/deadline authority.

Required repair: use monotonic elapsed state internally and expose wall-clock timestamps only diagnostically.

Disposition: `ADAPT AFTER REPAIR`.

### 3.4 Provider lineage / false independence

Examples:

- Efinance often reaches Eastmoney;
- AKShare EM reaches Eastmoney;
- another direct Eastmoney adapter may reach the same upstream backend.

A fallback across wrappers over the same upstream is useful for client-library failures but is **not independent-source reconciliation**.

Required new metadata:

- `provider_adapter_id`;
- `upstream_lineage_id` / upstream family;
- endpoint/source family;
- independence class for reconciliation.

Disposition: `ADAPT AFTER LINEAGE MAP`.

### 3.5 Global priority promotion from configuration

Upstream may promote Tushare to high generic priority when a token is present.

Radar rule:

> configured != best for every capability.

A token can change availability/cost status, but provider ranking remains per capability: daily history, intraday, calendar, fundamentals, realtime quote, etc.

Disposition: `ADAPT AFTER CAPABILITY-SPECIFIC ROUTING`.

## 4. Strong additional candidate: TickFlow

Upstream already has a substantial `TickFlowFetcher`, including:

- A-share daily K-lines;
- realtime quote path;
- market review/index breadth support;
- explicit request timeout;
- API-key capability handling;
- cache/capability negative-cache controls using monotonic time;
- Shanghai/Shenzhen/Beijing symbol conversion;
- volume-lot to share conversion;
- timezone handling;
- adjustment-mode configuration;
- dedicated tests.

High-value properties:

- structured API rather than only webpage scraping;
- explicit timeout;
- broad A-share coverage;
- upstream implementation already contains useful capability and permission handling.

Audit cautions:

- current service entitlement/cost/rate limits must be verified live;
- provider timestamp semantics need empirical proof;
- malformed numeric conversion still needs Radar's stricter evidence model;
- API availability must not become Currentness proof;
- source independence relative to other providers must be established.

Disposition: `HIGH-PRIORITY ADAPT / EMPIRICAL-VALIDATION CANDIDATE`.

TickFlow must be added to the A-share capability inventory before final provider rankings.

## 5. AKShare-specific useful upstream work

The upstream `AkshareFetcher` contains a process-isolated timeout helper for potentially hanging history calls:

- explicit `spawn` multiprocessing context;
- generation-local Pipe;
- child Process;
- finite history-call timeout;
- terminate -> bounded join -> kill -> bounded join fallback.

This is valuable mature engineering evidence and independently supports the Provider Worker decision that a timeout should bound the execution capability, not merely caller patience.

However this helper is for a bounded/stateless call and must **not** be substituted directly for the frozen long-lived LiveFeed provider-worker supervisor.

Disposition: `TEST-REUSE / METHOD HARVEST`.

## 6. Pytdx upstream disposition

Upstream `PytdxFetcher` is mature application code with:

- multiple server candidates;
- connection timeout;
- cooldown;
- retry/backoff;
- explicit unsupported-market handling;
- history normalization.

But its underlying `rainx/pytdx` project is archived.

Additional observed repair items:

- cooldown uses wall clock in observed code paths;
- direct server list can age;
- BSE support is rejected;
- date-count retrieval uses trading-day estimation rather than authoritative calendar semantics;
- provider transport recovery does not prove data freshness/currentness.

Recommended path:

1. harvest tests/server failover/failure cases;
2. compare adapter semantics with `mootdx` / its underlying maintained TDX stack;
3. do not newly standardize Radar on archived `pytdx` merely because upstream already uses it.

Disposition: `TEST-REUSE / MIGRATE IMPLEMENTATION CANDIDATE`, not direct CORE adoption.

## 7. BaoStock / TuShare upstream disposition

The existence of upstream adapters is useful because integration shape and normalization tests can be harvested.

But provider acceptance still requires current empirical service checks:

### TuShare

- token/permission capability inventory;
- point/cost requirements;
- per-endpoint frequency limits;
- actual update delay;
- adjustment/calendar/corporate-action semantics.

Disposition: `ADAPT FOR STRUCTURED DATA AFTER CAPABILITY PROBE`.

### BaoStock

- current service/package availability;
- history correction behavior;
- adjustment semantics;
- calendar/fundamental freshness;
- license/package provenance.

Disposition: `HISTORY/BACKFILL RECONCILIATION AFTER PROBE`.

## 8. Migration classification matrix

| Upstream asset | Decision | Main reason |
| --- | --- | --- |
| `BaseFetcher` interface idea | ADAPT | Mature provider-neutral boundary |
| `DataFetcherManager` routing idea | ADAPT | Mature fallback orchestration; replace global ranking with capability routing |
| `DataCapabilityService` | ADAPT / TEST-REUSE | UNKNOWN/degraded/capability semantics largely align |
| `UnifiedRealtimeQuote` provenance fields | ADAPT | Good source/fallback/timestamp evidence shape |
| `UnifiedRealtimeQuote.is_stale` TTL authority | REJECT AS CURRENTNESS AUTHORITY | Wall-age != semantic progress |
| `safe_float` normalization | ADAPT AFTER REPAIR | Collapses malformed and missing evidence |
| CircuitBreaker state machine | ADAPT AFTER REPAIR | Use monotonic elapsed clock |
| upstream provider fallback tests | TEST-REUSE | Mature failure-path coverage |
| AKShare history process-timeout helper | METHOD / TEST-REUSE | Real execution kill boundary pattern |
| TickFlow adapter | HIGH-PRIORITY ADAPT CANDIDATE | Structured A-share API + broad capability |
| Efinance/AKShare EM dual fallback | ADAPT WITH LINEAGE | Same upstream family may not be independent |
| Pytdx implementation | TEST-REUSE / MIGRATE | Underlying dependency archived |
| TuShare adapter | ADAPT AFTER CAPABILITY PROBE | Structured API, entitlement-dependent |
| BaoStock adapter | ADAPT FOR BACKFILL AFTER PROBE | Historical/reconciliation role |
| Tencent direct quote/day K | ADAPT / EMPIRICAL TEST | Useful lightweight independent client path; timestamp semantics must be proven |

## 9. Proposed A-share target architecture

```text
A-share Capability Registry
  |
  +-- quote.realtime
  |     Tencent direct / TickFlow / TDX-family / AKShare sub-sources
  |
  +-- bars.intraday (15m / 1H)
  |     TDX-family / TickFlow / independently validated source
  |
  +-- bars.daily + historical backfill
  |     TuShare / TickFlow / BaoStock / upstream fallback adapters
  |
  +-- calendar/reference
  |     structured provider + exchange/reference reconciliation
  |
  +-- fundamentals/corporate actions
  |     TuShare / BaoStock / selected AKShare
  |
  +-- sectors/concepts/breadth
        AKShare / TickFlow / selected upstream adapters

Each route
  -> provider adapter identity
  -> upstream lineage identity
  -> normalization preserving malformed vs missing
  -> Data Health
  -> currentness/progress qualification where applicable
  -> cross-provider reconciliation
  -> downstream Radar
```

## 10. Immediate implementation order

### A0 — inventory / no behavior change

1. inventory upstream provider adapters and tests against current Stock Razor main;
2. define capability IDs needed by Radar: realtime quote, 15m, 1H, daily, calendar, ETF/index, fundamentals, corporate actions, sectors;
3. add provider/upstream-lineage metadata contract;
4. map which upstream tests can be imported unchanged vs rewritten.

### A1 — normalization contract

1. import/adapt unified quote provenance shape;
2. replace `safe_float` semantics with Radar malformed/missing contract;
3. make Data Health the only permission authority;
4. preserve stale age as diagnostic evidence only.

### A2 — provider candidates

Empirically test in this order:

1. TickFlow structured A-share paths if credentials/access are available;
2. Tencent direct lightweight quote path;
3. TDX-family path using a maintained implementation candidate;
4. AKShare sub-sources with explicit upstream lineage;
5. TuShare structured history/reference capabilities;
6. BaoStock history/backfill.

### A3 — reconciliation / failover

Only after A1/A2 semantics are proven:

- cross-source price/bar reconciliation;
- T+1 daily diff report;
- failure/cooldown tests;
- stale-good-state revocation;
- automatic fallback with lineage awareness;
- Shadow validation.

## 11. Cross-window handoff

Any other chat/development window handling A-share interfaces should read:

1. `tools/open_source_intake/A_SHARE_DATA_PROVIDER_HARVEST_BATCH_2026_09_09.md`
2. `tools/open_source_intake/A_SHARE_UPSTREAM_PROVIDER_MIGRATION_MATRIX_2026_09_09.md`
3. the main Open-Source Harvest Ledger / PR #31.

No conversational summary should override these durable artifacts.

## Governing decision

> Reuse the upstream A-share engineering aggressively, but promote only the semantics that survive Radar's stricter Data Health, provenance, Currentness and validation contracts.
