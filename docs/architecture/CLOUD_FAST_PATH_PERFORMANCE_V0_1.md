# STOCK RAZOR Cloud Fast Path Performance V0.1

Status: SPEC / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## 1. Objective

The cloud path must be measured against the low-latency OpenD baseline, not merely judged as "available".

Target path:

```text
Cloud OpenD persistent stream
  -> canonical 1m
  -> incremental 5m / 15m / 1h
  -> Radar incremental analysis
  -> Secure MCP / Main Control
  -> ChatGPT final decision
```

Performance work MUST NOT reduce analysis dimensions, weaken freshness/completeness/correctness checks, or bypass any qualification, Radar-admission, or execution-safety gate.

## 2. Empirical local OpenD baseline

Observed local-PC OpenD PRIMARY measurements:

| Measurement | Observed |
| --- | ---: |
| 13-symbol batch snapshot | 196.91 ms |
| OpenD connect | 2.76 ms |
| OpenD core fetch | 199.67 ms |
| symbols successful | 13 / 13 |
| provider return | RET_OK |
| retry count | 0 |
| fallback count | 0 |
| consecutive core-fetch runs | 254.93 -> 205.58 -> 199.67 ms |

This is a benchmark/reference path. Cloud must remain independently usable while the personal PC is offline.

## 3. Performance SLOs

| Layer | Target |
| --- | ---: |
| canonical read | < 300 ms |
| Radar incremental analysis | < 500 ms |
| Data -> Radar internal chain | < 1 s |
| Main Control / ChatGPT usable result | normally within a few seconds |

A single best-case sample is insufficient. SLO evaluation requires sustained measurements and percentile distributions.

## 4. Required telemetry contract

Every measured fast-path sample SHOULD carry a correlation/request ID and exact runtime provenance.

Required timing fields:

- `provider_latency_ms`
- `canonical_latency_ms`
- `radar_analysis_latency_ms`
- `mcp_latency_ms`
- `chatgpt_access_latency_ms`
- `e2e_latency_ms`

Required quality/health fields:

- `freshness_ms` or semantically equivalent source-age field
- `provider`
- `delivery_mode`
- `data_completeness`
- `data_correctness_state`
- `analysis_quality_state`
- `success`
- `retry_count`
- `fallback_count`
- `fallback_provider`
- exact `repo_sha` / runtime provenance

Required rolling statistics:

- P50
- P95
- P99
- success rate
- retry rate
- fallback rate
- freshness distribution

Percentiles MUST be computed from comparable samples with explicit sample count and window.

## 5. Clock boundaries

Latency fields MUST have non-overlapping semantics.

Recommended boundaries:

1. **provider latency**: provider request/stream event handling start -> normalized provider payload accepted.
2. **canonical latency**: canonical read request -> canonical payload returned.
3. **Radar analysis latency**: incremental analysis start -> precomputed Radar state committed.
4. **MCP latency**: MCP tool invocation -> tool result available at MCP boundary.
5. **ChatGPT-access latency**: Main Control/assistant tool request -> usable structured result received.
6. **E2E latency**: qualified source event/data availability -> Main Control receives the complete decision-ready state.

Freshness is separate from processing latency. A fast read of stale data MUST NOT pass.

## 6. Fast-path design rules

The cloud implementation SHOULD use:

- persistent OpenD connection/stream
- resident canonical cache
- canonical 1m as normalized intraday base
- incremental 5m / 15m / 1h aggregation
- incremental Radar compute
- precomputed Radar state
- secure read-only MCP consumption
- cache/history warm-start only when provenance and settlement semantics are qualified

The hot path MUST NOT, on each user request:

- reconnect to OpenD without necessity
- refetch the full historical window
- rebuild every timeframe from the full history
- recompute the full Radar state if only incremental state changed
- invoke fallback providers when PRIMARY is healthy merely for convenience
- trade analysis quality for latency

Cross-checks may run asynchronously from the hot decision path only when their absence does not weaken the required decision-quality contract.

## 7. Provider priority

For US market data:

1. OpenD = PRIMARY
2. Cloud Radar/OpenD Direct
3. Alpaca = fallback / cross-check
4. Web = GC / macro / news supplementation

When the personal computer is online, local OpenD may be used as a low-latency benchmark or PRIMARY test path. Cloud must not depend on that computer being online.

## 8. PASS gate

A performance qualification is PASS only when all five dimensions pass:

```text
FAST
+ FRESH
+ COMPLETE
+ CORRECT
+ FULL-QUALITY ANALYSIS
= PASS
```

Examples that MUST fail:

- fast but incomplete
- fast but stale
- correct but routinely takes tens of seconds
- lower latency achieved by removing analysis dimensions
- hidden retries/fallbacks inflating tail latency
- cache hit reported as fast while the cache is materially stale
- successful transport while Radar state is provenance-mismatched

Performance qualification does NOT imply Radar admission or execution authorization.

## 9. Measurement phases

### Phase A — Instrumentation

Add unified layer-level timing and quality fields to the existing canonical/Radar/MCP path. Reuse existing semantically correct fields such as `source_age_seconds`, `read_latency_ms`, and bar latency rather than creating duplicate meanings.

### Phase B — Controlled benchmark

Measure at minimum:

- local OpenD baseline
- cloud OpenD provider path
- canonical hot read
- canonical cold/warm read where relevant
- incremental Radar compute
- MCP read
- full Data -> Radar -> MCP path
- Main Control access path

Report sample count, P50/P95/P99, freshness, success/retry/fallback rates.

### Phase C — sustained runtime qualification

Run long enough to include:

- normal active market periods
- bursty update periods
- reconnect/restart
- stale/no-data
- fallback activation
- recovery to PRIMARY
- symbol-pool batch reads

No single green workflow is sufficient evidence.

## 10. Full-quality analysis invariant

The performance path must retain the approved analysis contract, including relevant:

- regime
- location
- structure
- relative strength
- volume/price behavior
- multi-timeframe state
- setup / entry gate / trigger
- invalidation
- risk permission / sizing context
- event/macro/options context where required by the decision contract

If any required dimension is unavailable or stale, the result must degrade/fail explicitly rather than silently omit the dimension.

## 11. User-experience target

Normal command:

```text
获取
```

Expected orchestration:

1. choose the fastest qualified data path automatically
2. acquire the full configured watch pool plus gold context
3. run complete incremental Radar analysis
4. Main Control produces final research judgment
5. return BUY / ADD / HOLD / REDUCE / EXIT-style research output within seconds under normal conditions

The result must include enough provenance/quality state for Main Control to distinguish PRIMARY, retry, fallback, stale, partial, or blocked conditions.

## 12. Existing-governance boundary

Performance optimization may improve throughput, cache locality, aggregation, scheduling, precompute, protocol overhead, and payload size.

It MUST NOT:

- set `RADAR_ADMISSION=PASS`
- change `LIVE_TRADE=NO`
- bypass currentness/timestamp/closure/provenance gates
- weaken fail-closed behavior
- silently substitute fallback data
- promote UNKNOWN without evidence

## 13. V0.1 engineering priority

The first implementation change should be a unified performance-measurement contract and benchmark harness over the existing path, not a parallel data system.

Only after measurement identifies the dominant latency contributors should implementation optimization PRs be prioritized.

## Repeated cache samples are not repeated provider events (V0.2)

The 30-iteration AWS read benchmark invokes existing cached readers. In prior
reports it repeated a single worker's last callback-processing duration,
REST provider-request duration, Radar compute duration, and Data-to-Radar
elapsed time 30 times. Reporting those duplicated cached values as P50/P95/P99
would incorrectly suggest 30 independent market events.

The read benchmark now **samples only work performed on each iteration**:
canonical cache read and Radar-cache read durations. The repeated worker
telemetry fields remain `null` in the `FastPathSample` histogram, with
`sample_count=0` and `missing_count=30`; provider RTT, Radar compute,
Data-to-Radar and E2E are still NOT_VERIFIED. This does not erase existing
worker telemetry: US read diagnostics surface one `cached_last_*` observation
for callback processing, Radar analysis and Data-to-Radar, marked
`cached_worker_telemetry_unique_event_qualified=false`. CN per-symbol
diagnostics likewise expose a *single* prior cached REST-request duration,
not a percentile series.

US market-state diagnostics now use the shared Futu session mapping, so
`PRE_MARKET_BEGIN` is `premarket`, rather than `UNKNOWN`. This is
classification only; it does not promote source currentness.

A future valid latency distribution must join distinct source-event IDs and
timing windows with Canonical and Radar analysis executions. Merely reading the
same cached metrics repeatedly is not an acceptable shortcut to <1s SLO.
