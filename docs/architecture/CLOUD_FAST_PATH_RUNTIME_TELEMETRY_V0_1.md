# Cloud Fast Path Runtime Telemetry V0.1

Status: CI CANDIDATE — research-only. `RADAR_ADMISSION=BLOCKED`; `LIVE_TRADE=NO`.

This slice adds observation-only telemetry to existing AWS US/CN paths. No routing,
subscription, trading, funding, or notification behavior changes.

## Measurement ownership and meaning

| Field | Source and boundary | NOT equivalent to |
| --- | --- | --- |
| `provider_callback_processing_latency_ms` | US OpenD SDK callback enters → payload normalization → local sink returns (last callback), via adapter diagnostics/health | provider network RTT; tick delay; data freshness |
| `provider_request_path_latency_ms` | CN cloud request-path elapsed time as reported in per-frame observation; fallback/retry may be included | a single provider's pure RTT |
| `canonical_latency_ms` | measured read-only canonical access, including cache | source-to-controller delivery |
| `radar_analysis_latency_ms` | US worker poll/evaluation or CN evaluator, measured with monotonic time only when fresh analysis runs | cached radar read; complete signal quality |
| `radar_read_latency_ms` | read-only precomputed analysis fetch | radar analysis computation |
| `data_to_radar_latency_ms` | source snapshot emitted UTC → worker computation finished UTC on a fresh analysis | provider→canonical→Radar full end-to-end |
| `mcp_latency_ms` / `chatgpt_access_latency_ms` / `e2e_latency_ms` | **UNKNOWN**, not instrumented in this slice | a sum inferred from readers |
| `provider_latency_ms` | **UNKNOWN** until exact provider transport measurement is available | OpenD callback processing or CN request path |

All fields without direct observations stay `None`. The US adapter's
`provider_callback_latency_ms_last/max/mean/sample_count` are legacy-named
diagnostic keys; the benchmark explicitly classifies them as **callback
processing**, not network RTT.

## Critical measurement cautions

- The benchmark reads snapshots in a loop; repeated identical source sequences
  are **not independent provider or Radar compute observations**. Therefore
  compute/provider percentiles from repeated reads are diagnostic only, not
  production SLO qualification. Use unique source-sequence observations for
  proper sustained-window P50/P95/P99.
- CN aggregate canonical read time is `None` if any requested symbol has
  missing read timing. Provider request-path representative is the maximum
  observed among all requested symbols, only when all requested symbols report
  a value; this is **not** an end-to-end sum.
- Callback latency is measured with a monotonic clock, including local sink
  processing. It does not establish data currentness or OpenD quote entitlement.
- Existing research worker polls are not necessarily below 1s. A defined
  <1s Data→Radar goal is **not** proof that it has been achieved.
- `UNCHANGED` or a blocked US Radar evaluation emits no compute latency;
  `UNCHANGED` CN reuses prior result and emits no new compute latency.
- Read-only readers accept older heartbeats without telemetry (UNKNOWN), but
  reject malformed, inconsistent, negative, or fabricated new timing fields.
- Retry counts remain UNKNOWN when absent. A positive CN fallback observation
  is countable, but a missing fallback field does not certify zero fallbacks.
- Session freshness, completeness, correctness, analysis quality and every
  admission gate remain independent of observed latency.

## Validation

- Offline adapter/reader, AWS installer/verifier contract tests.
- Offline benchmark provenance and UNKNOWN tests.
- Fresh exact-head GitHub Research Radar and CI gates before merging.
- AWS runtime deployment and real sustained telemetry collection are **not**
  established by these contract tests.
