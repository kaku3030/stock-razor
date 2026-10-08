# STOCK RAZOR CN Runtime Evidence Ingest V0.1

Status: STACKED IMPLEMENTATION / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

Translate the existing cloud A-share observation snapshot into separate
Provider Lifecycle evidence for `eastmoney` and `tencent`.

The upstream runtime file is:

`/run/stock-razor-cn-eastmoney/latest-observation.json`

The existing observer already records per-frame:

- `provider_used`
- `provider_lineage`
- `fallback_from`
- `fallback_reason`
- `status`
- currentness qualification
- route request latency

This adapter does not create a parallel provider selector.

## Evidence attribution

Static `provider_lineages=["eastmoney","tencent"]` is identity metadata only.
It is **not** runtime health evidence.

Provider evidence comes only from each symbol/timeframe:

- direct `provider_used=eastmoney` -> Eastmoney success fact;
- `provider_used=tencent` with `fallback_from=eastmoney` -> Eastmoney negative
  evidence plus Tencent fallback success fact;
- a BLOCKED frame carrying
  `...|TENCENT:<error>` -> negative evidence for both attempted lineages.

Top-level `providers_used` must exactly match per-frame evidence.

## Health mapping

Positive fetch evidence does not prove provider-wide HEALTHY:

- direct Eastmoney success -> Eastmoney `UNKNOWN`;
- successful Tencent fallback -> Tencent `UNKNOWN`;
- observed Eastmoney fallback trigger -> Eastmoney `DEGRADED`;
- observed Tencent fallback failure -> Tencent `DEGRADED`.

The adapter does not claim `FAILED` from one scoped frame failure.

## Data-quality separation

The existing CN observer may prove Tencent BAR_END/currentness for a frame.
Those remain capability/data-quality facts.

V0.1 deliberately does not populate:

- `latency_ms` from route latency, because fallback route latency includes
  primary failure plus fallback work;
- `freshness_ms` from currentness or receipt time;
- Data Admission;
- Radar Admission;
- execution permission.

## Provenance

Every emitted lifecycle field retains:

- `emitted_at_utc`
- exact lowercase `repo_sha`
- `runtime_instance_id`
- sequence-scoped evidence ID
- concrete source `cn_eastmoney_cloud_observation`

The deployed snapshot must remain research-only and carry
`radar_admission=BLOCKED` and `live_trade=false`.

## Stacked-development note

This implementation is developed above the OpenD runtime-ingest slice and is
not eligible to merge until its prerequisite PRs are merged and the final diff
is rebuilt from current canonical `main` with fresh CI and Code Owner approval.
