# A-Share Intraday Capability Contract Candidate V0.1

Status: `DESIGN:CANDIDATE` — Harvest handoff for Architecture & Promotion Control Tower review. **NOT FROZEN.**

Scope: normalize provider capability/evidence for CN `15m` / `1H` K-line data before any provider is admitted as an intraday Currentness authority.

No implementation, routing, scoring, fallback, Currentness threshold, SHADOW/CORE, strategy, AI, or trading behavior is authorized by this document.

## Current evidence correction

Current external-provider evidence now confirms that **TickFlow full/API-key service exposes A-share minute K-lines including 15m and 60m**. The earlier Harvest note that authoritative external TickFlow 15m/1H capability evidence was unknown is historical and must not be treated as current truth.

This correction changes only the external-capability fact. It does **not** verify TickFlow timestamp start/end semantics, forming-bar behavior, session/lunch semantics, or Currentness eligibility, and the current Stock Razor `TickFlowFetcher` remains daily-K-line oriented.

Primary current evidence rule:

> `external method exists != Radar capability implemented != provider semantics verified != Currentness authority`

## Why this contract is needed

Current Stock Razor capability metadata is provider/dataset oriented (`quote.realtime`, `kline.daily`, etc.). External A-share sources expose 15m/60m data in several ways, but method availability alone cannot answer:

- whether the source is actually wired into Radar;
- whether two adapters are independent upstream evidence;
- whether a timestamp names bar start, bar end, or another provider-defined point;
- whether the newest row is forming or complete;
- how the 11:30–13:00 lunch break and exchange/session transitions are represented;
- whether values are adjusted and what volume/amount units mean;
- whether minute permission is actually entitled;
- whether a provider call can block the caller indefinitely;
- whether a capability is historical-only, diagnostic, or eligible for Currentness authority.

## Relationship to existing frozen / validated work

This candidate MUST reuse rather than duplicate:

- PR #40 `RealtimeSourceLineage` / reconciliation-independence substrate for `upstream_lineage_id` semantics;
- shared Data Health / Currentness architecture for final freshness authority;
- provider-specific evidence discipline used in Futu semantics work;
- malformed-vs-missing Data Reliability rule;
- provider blocking-isolation principles where synchronous calls can hang.

It MUST NOT create a provider-specific parallel Currentness engine.

## Proposed identity key

One capability observation should be identified by:

`(provider_id, adapter_id, upstream_lineage_id, market, instrument_kind, interval, access_mode)`

Where:

- `provider_id`: Radar provider identity, e.g. `tushare`, `akshare`, `pytdx`;
- `adapter_id`: concrete Stock Razor adapter path;
- `upstream_lineage_id`: independent upstream family from PR #40 semantics;
- `market`: `cn`;
- `instrument_kind`: at minimum `STOCK | ETF | INDEX`;
- `interval`: `15M | 1H`;
- `access_mode`: one of the evidence categories below.

Different adapters over the same upstream lineage are **not independent corroboration**.

## Proposed access-mode vocabulary

Design candidate only:

- `REALTIME_PUSH`
- `REALTIME_REQUEST`
- `CURRENT_DAY_REPLAY`
- `HISTORICAL_REQUEST`
- `LOCAL_FILE_HISTORY`

Access mode stays separate from Currentness eligibility. A `REALTIME_REQUEST` endpoint may still be semantically insufficient for Currentness.

## Proposed evidence / semantics record

### A. Identity / scope

- `provider_id: str`
- `adapter_id: str`
- `upstream_lineage_id: str | UNKNOWN`
- `market: cn`
- `instrument_kind: STOCK | ETF | INDEX`
- `interval: 15M | 1H`
- `access_mode`
- `endpoint_semantic_id`

### B. Admission state

- `radar_implementation_status`:
  - `NOT_IMPLEMENTED`
  - `IMPLEMENTED_NOT_VALIDATED`
  - `VALIDATING`
  - `ADMITTED`
- `provider_availability_status`
- `entitlement_status`:
  - `NOT_REQUIRED`
  - `REQUIRED_UNVERIFIED`
  - `VERIFIED_AVAILABLE`
  - `VERIFIED_UNAVAILABLE`
  - `UNKNOWN`

A configured token/API key is not entitlement proof.

### C. Source timestamp semantics

- `source_timestamp_field`
- `source_timezone`
- `timestamp_boundary_semantic`:
  - `BAR_START`
  - `BAR_END`
  - `PROVIDER_DEFINED_OTHER`
  - `UNKNOWN`
- `timestamp_precision`
- `cross_request_comparable: VERIFIED | PARTIAL | UNKNOWN`

No start/end value may be filled from intuition, sample appearance, another provider's behavior, or a third-party wrapper claim.

### D. Forming / completion semantics

- `forming_bar_included`: `YES | NO | CONDITIONAL | UNKNOWN`
- `forming_bar_mutates_same_identity`: `YES | NO | UNKNOWN`
- `completion_marker_field: str | NONE_OBSERVED | UNKNOWN`
- `completion_inference_authorized: bool`

`completion_inference_authorized=True` requires evidence. Absence of a completion flag does not authorize a clock heuristic.

### E. Session / expected-silence semantics

- `session_model_id`
- `morning_session_alignment`
- `lunch_break_behavior`
- `afternoon_session_alignment`
- `close_final_bar_behavior`
- `suspension_behavior`
- `zero_trade_interval_behavior`
- `temporary_closure_authority`

Exchange trading hours are an input to this group, but exchange hours alone do not define provider bar construction.

### F. Price / volume semantics

- `adjustment_mode`: `NONE | FORWARD_ADJUSTED | BACKWARD_ADJUSTED | CALLER_SELECTABLE | UNKNOWN`
- `volume_unit`
- `amount_unit`
- `lot_size_semantics`
- `numeric_missing_semantics`
- `numeric_malformed_semantics`

Malformed numeric evidence must remain distinguishable from genuinely missing values.

### G. Retrieval constraints

- `max_rows_per_call`
- `max_lookback`
- `pagination_model`
- `publication_delay_semantic`
- `rate_limit_semantic`
- `blocking_risk`: `BOUNDED_BY_PROVIDER | CALLER_BOUNDED_ISOLATION_REQUIRED | UNKNOWN`

A caller-side thread timeout that leaves a blocking provider operation alive does not prove hard execution isolation.

### H. Evidence provenance

- `official_evidence_refs[]`
- `controlled_observation_refs[]`
- `sdk_version`
- `provider_service_version` if known
- `observed_symbol_scope[]`
- `observed_date_scope[]`
- `evidence_status`: `UNKNOWN | PARTIALLY_VERIFIED | VERIFIED_TESTED_SCOPE | SOURCE_VERIFIED`

Tool/test green status remains separate from provider evidence status.

## Proposed Currentness eligibility state

Design candidate only; no production enum is authorized yet.

- `HISTORICAL_ONLY`
- `DIAGNOSTIC_ONLY`
- `CURRENTNESS_CANDIDATE`
- `CURRENTNESS_ELIGIBLE`

### Hard gates for `CURRENTNESS_ELIGIBLE`

All of the following must be non-UNKNOWN and evidenced for the exact provider/market/instrument/interval/access mode:

1. provider/adapter identity is explicit;
2. upstream lineage identity is explicit for reconciliation;
3. runtime entitlement/capability is verified where required;
4. source timestamp field and timezone are known;
5. timestamp boundary semantic is known;
6. forming-bar inclusion/completion behavior is known;
7. morning/lunch/afternoon/close behavior is known;
8. suspension / expected-silence behavior is bounded sufficiently to avoid false stale;
9. adjustment and volume/amount units are known;
10. malformed-vs-missing behavior is explicit;
11. blocking/failure behavior has an accepted containment strategy;
12. controlled provider observation exists in target scope;
13. independent review accepts the evidence mapping;
14. governance explicitly promotes the capability.

Failure of any hard semantic gate must **not** be compensated by source count, confidence score, provider reputation, low latency, or agreement with another adapter.

## Reconciliation rule

Reconciliation works over **independent upstream lineage groups**, not adapter count.

Examples:

- Efinance 15m + AkShare EM 15m agreeing = one Eastmoney lineage observation, not two votes.
- Tushare + TDX agreeing may be independent evidence only if both capability records meet their own semantic gates.
- unknown lineage remains visible for diagnostics but is not eligible to increase independence count.

No numeric decision weighting is defined in V0.1.

## Current candidate mappings

### Efinance / Eastmoney

- external capability: `klt=15` and `klt=60` are documented;
- current Stock Razor adapter: `klt=101` daily path only;
- lineage: Eastmoney;
- timestamp/forming/session semantics: UNKNOWN for Currentness purposes;
- current eligibility: `NOT_IMPLEMENTED` as Radar intraday capability.

### AkShare / Eastmoney minute routes

- official AkShare docs expose A-share and ETF minute endpoints with `period` including `15` and `60`;
- current Stock Razor AkShare fetch paths are daily-oriented;
- lineage: Eastmoney for the EM minute route, therefore not independent from Efinance;
- official wrapper docs expose a time field but do not define bar-start vs bar-end semantics;
- current eligibility: not admitted.

### TDX / PyTDX / mootdx

- protocol/wrapper capability: category `1` = 15-minute and category `3` = 1-hour;
- current Stock Razor PyTDX unified fetch path hard-codes daily category `9`;
- lineage: TDX-family candidate, distinct from Eastmoney/Tushare;
- timestamp/session/blocking semantics: require controlled audit;
- current eligibility: not admitted.

### Tushare

- official `rt_min` / `rt_min_daily` expose A-share 15MIN/60MIN;
- official ETF minute services expose 15MIN/60MIN; historical ETF minute API exposes 15min/60min;
- minute access requires explicit permission/entitlement;
- documented output includes trading time plus OHLC, volume in shares and amount in yuan;
- docs do not define aggregated bar timestamp as start vs end and do not close forming-bar semantics;
- current Stock Razor Tushare history path is not an admitted 15m/1H contract;
- current eligibility: strong `CURRENTNESS_CANDIDATE` research lane after adapter + entitlement + semantics validation, not eligible yet.

### BaoStock

- provider ecosystem/source documentation exposes stock historical 15m/60m via `query_history_k_data_plus`; minute data carries `date,time,OHLC,volume,amount,adjustflag` and does not include index minute data;
- current Stock Razor adapter is daily-only;
- current Harvest has not established an official-provider realtime/current-day publication contract suitable for Currentness;
- a third-party .NET implementation describes `time` as bar end, but that is **not accepted as provider-authoritative semantics** under this governance standard;
- current eligibility: `HISTORICAL_ONLY` candidate unless controlled/provider-authoritative evidence proves more.

### TickFlow

- **CURRENT CORRECTED FACT:** official TickFlow documentation says A-share minute K-lines support `1m/5m/15m/30m/60m` in the full API-key service; free service explicitly excludes minute K-lines;
- official API also exposes current-day intraday K-line endpoints with `15m` / `60m` period options;
- therefore external interval capability and API-key entitlement requirement are `SOURCE_VERIFIED`;
- current Stock Razor `TickFlowFetcher` remains daily-K-line/realtime-quote oriented and does not admit these minute endpoints as `kline.15m` / `kline.1h`;
- official docs expose `timestamp` / `trade_time`, but current Harvest evidence does not define their bar-start vs bar-end meaning or forming-bar completion semantics;
- current eligibility: `NOT_IMPLEMENTED` in Radar; provider semantics still insufficient for Currentness.

## Exchange-session authority already known

For standard stock auction trading, current SSE rules define:

- opening call auction: 09:15–09:25;
- continuous auction: 09:30–11:30 and 13:00–14:57;
- closing call auction: 14:57–15:00;
- trading interruption does not automatically extend the trading day.

SZSE publishes the same standard continuous-auction/lunch structure for securities.

These exchange facts can define **session expectation inputs**. They do not define whether a provider's 15m/60m timestamp labels interval start/end, how a provider treats the closing call auction, or whether a current row is forming.

## Minimal implementation order if Control Tower accepts the shape

Proposed only, not authorization:

1. freeze vocabulary/field shape in docs;
2. implement immutable capability/evidence types only;
3. expose read-only capability records through `DataCapabilityService` without routing changes;
4. add anti-shrink and fail-closed tests;
5. populate records only with proven facts; leave unknowns explicit;
6. build provider-specific evidence harnesses;
7. only after evidence closure, consider Currentness-candidate integration;
8. routing/fallback/decision changes remain a separate promoted slice.

## Exit criteria for this design candidate

Control Tower review should answer:

- Does this duplicate an existing frozen model? If yes, merge/reuse rather than create a parallel type.
- Is `upstream_lineage_id` sourced from PR #40 rather than redefined?
- Are Currentness eligibility and provider evidence separate dimensions?
- Are all UNKNOWN states fail-closed?
- Is entitlement explicit rather than inferred from configuration?
- Are lunch-break / suspension / forming-bar semantics first-class?
- Is there hidden compensatory scoring? There must not be.
- Can the type be exposed read-only without changing routing?

Until those questions are accepted, this remains `DESIGN:CANDIDATE`, not FROZEN.
