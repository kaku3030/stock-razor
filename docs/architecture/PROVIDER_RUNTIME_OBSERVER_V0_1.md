# STOCK RAZOR Runtime Provider Observer / Evidence Provenance V0.1

Status: SPEC + IMPLEMENTATION / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

Provider lifecycle state must be backed by runtime evidence instead of static
capability notes or remembered assumptions. This slice adds a narrow observer
that records each lifecycle field with its own provenance.

Required provenance:

- `observed_at` — timezone-aware time when this evidence was observed
- `source` — concrete probe / collector / API / runtime source
- optional `runtime_id`
- optional exact `repo_sha`
- optional provider/runtime `error_code`
- optional `evidence_id`

The observer does **not** convert receipt time into market freshness.

## Separation of concerns

| Layer | May decide | Must not decide |
| --- | --- | --- |
| Runtime Provider Observer | what was observed and provenance | Data Admission, fallback authorization, Radar admission, spend, execution |
| Provider Health assessment | lifecycle health such as EXPIRED / EXHAUSTED / WARNING | market-data currentness or execution |
| Data Admission | freshness / coverage / timestamp-currentness / latency / sanity gates | provider billing actions or live execution |
| Radar Admission | whether qualified data/analysis may enter Radar | live trading |
| Execution authorization | later explicit execution safety gate | automatic promotion from upstream PASS |

Therefore:

`Provider Health PASS != Data Admission PASS != Radar Admission PASS != Execution Authorization`.

## Merge rules

Evidence is merged independently per lifecycle field:

1. newer `observed_at` replaces older evidence for that field;
2. older evidence cannot roll a field backward;
3. equal-time conflicting values are rejected fail-closed;
4. static registry identity cannot be overwritten by runtime evidence;
5. missing evidence remains `UNKNOWN` / `None`; it is never guessed as zero or healthy;
6. a candidate observation is validated transactionally before observer state changes.

This allows, for example, AWS cost and budget evidence to originate from
different APIs while retaining distinct provenance.

## Current scope

V0.1 supports lifecycle fields already defined by
`ProviderLifecycleRecord`, including credential, quota, billing, latency,
freshness, coverage, health, cost, usage, and capability evidence.

The observer is in-memory and deterministic. Persistence, provider-specific
collectors, API polling, AWS Cost Explorer ingestion, Twelve Data quota
ingestion, Tavily usage ingestion, and notification delivery are later slices.

## Explicit non-goals

This PR does not:

- promote `RADAR_ADMISSION`;
- change `LIVE_TRADE=NO`;
- mark Eastmoney healthy without Eastmoney evidence;
- treat fallback availability as fallback qualification;
- infer market freshness from `observed_at`;
- authorize recharge, plan upgrades, paid features, billing-limit increases, or auto recharge;
- create alerts or send notifications;
- create Paper or live orders.

## Next integration slice

Provider-specific adapters may emit `ProviderRuntimeObservation` values into
the observer. Those adapters must expose exact evidence rather than translating
unknown values into optimistic defaults.

Alert Engine and Notification Gateway remain downstream of verified provider
health and evidence provenance.
