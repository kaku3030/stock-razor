# STOCK RAZOR Cloud Fast Path Metrics V0.1

Status: IMPLEMENTATION CANDIDATE / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Purpose

Implement the first runtime-facing slice required by
`CLOUD_FAST_PATH_PERFORMANCE_V0_1.md`: a unified, fail-closed measurement
contract plus a read-surface benchmark harness.

The contract separates:

- provider latency;
- canonical read latency;
- Radar analysis/compute latency;
- Radar read latency;
- Data-to-Radar latency;
- MCP latency;
- ChatGPT-access latency;
- end-to-end latency;
- freshness.

A fast value from one layer MUST NOT be copied into another layer.

## Existing surfaces

The harness reuses the already-merged read-only cloud surfaces:

- US canonical snapshot reader;
- US precomputed Radar reader;
- CN cloud observation reader;
- CN precomputed Radar reader.

It performs no provider writes and no trading actions.

## Evidence boundary

The initial harness can immediately measure the local cloud read surfaces.
It deliberately leaves provider, Radar-compute, MCP transport, and true E2E
fields null until those layers publish or expose direct timing evidence.

Missing evidence produces `INCOMPLETE_EVIDENCE` / `UNKNOWN`, never PASS.

## SLO semantics

The documented internal SLOs remain:

- canonical read < 300 ms;
- Radar incremental analysis < 500 ms;
- Data -> Radar < 1 s.

These are performance facts only. They never imply Data Admission, Radar
Admission, signal confirmation, Paper admission, or execution authorization.

## Safety

Every sample is constrained to:

- `radar_admission=BLOCKED`;
- `live_trade=false`;
- `can_confirm_signal=false`.

Unsafe attempts fail construction.

## Next instrumentation

After this contract lands, wire direct measurements at the true owners:

1. US OpenD event/provider handling;
2. CN Eastmoney/Tencent request paths;
3. US/CN Radar worker compute/commit boundary;
4. MCP transport boundary;
5. Main Control access boundary.

Then run sustained windows with sample counts and P50/P95/P99 instead of
single best-case measurements.
