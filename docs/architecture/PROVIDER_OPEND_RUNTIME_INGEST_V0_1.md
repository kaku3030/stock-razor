# STOCK RAZOR OpenD Runtime Evidence Ingest V0.1

Status: IMPLEMENTATION / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

Connect the existing cloud US OpenD heartbeat to the Provider Lifecycle
observer without creating a second health system and without treating
transport/data facts as trading permission.

Input is the existing atomic runtime heartbeat:

`/run/stock-razor-us-livefeed/latest-heartbeat.json`

The adapter emits a `ProviderRuntimeObservation` for registry provider
`moomoo_opend`.

## Evidence mapped

The adapter preserves:

- `emitted_at_utc` -> provenance `observed_at`;
- exact `repo_sha`;
- `runtime_instance_id`;
- heartbeat `sequence` in the evidence ID;
- negative controller lifecycle evidence;
- latest accepted DATA receipt time as `last_success`;
- runtime facts such as delivery mode, bar closure, market state and canonical
  export state inside read-only capability evidence.

## Fail-closed health mapping

Negative transport facts may degrade health:

| Controller lifecycle | Provider health evidence |
| --- | --- |
| FAILED | FAILED |
| DEGRADED | DEGRADED |
| RECONNECTING | DEGRADED |
| DISCONNECTED | DEGRADED |
| CONNECTED / CONNECTING / SUBSCRIBING | UNKNOWN |
| LIVE | rejected under current contract |

A positive transport state is deliberately **not** promoted to HEALTHY.

## Separation rules

The adapter does not derive:

- `freshness_ms` from heartbeat receipt time or `last_push_utc`;
- provider latency;
- market-data coverage;
- Data Admission;
- fallback authorization;
- Radar Admission;
- execution permission.

`delivery_mode=REALTIME` and `bar_closure=PROVEN` remain observed facts only.

The input heartbeat must continue to contain:

- `radar_admission=BLOCKED`
- `live_trade=false`

Any violation is rejected rather than normalized away.

## Recovery semantics

When a newer heartbeat moves from a negative controller state back to
CONNECTED, current `failure_reason` becomes `None` and health returns to
UNKNOWN. Historical `last_failure` remains recorded until newer actual
failure evidence replaces it.

This intentionally distinguishes "transport recovered" from "provider fully
qualified healthy".

## Non-goals

V0.1 does not deploy or read the heartbeat file itself. It defines the
deterministic adapter and observer ingest boundary. File/runtime wiring and
other providers (Eastmoney/Tencent, Alpaca, Twelve Data, AI/search/cost
providers) remain later slices.
