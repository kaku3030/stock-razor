# MCP source-status latency: measurement boundaries

This adds *local cache-reader execution timings* to the existing read-only `get_market_source_status` response. The three `sources.*.local_reader_latency_ms` numbers measure local Python reader invocation only, and `read_latency_ms` measures total in-process aggregation. They **do not** measure TickFlow REST, OpenD provider requests, market exchange timestamps, network transport, MCP connector overhead, Radar inference, mobile notifications or execution.

`latency_scope=LOCAL_CACHE_READERS_ONLY`, `end_to_end_latency=NOT_MEASURED`, and `market_data_freshness_latency=NOT_MEASURED` prevent misinterpretation.

### Existing independent observations (do not conflate)

- Oct 9 AWS Tokyo TickFlow Premium REST smoke: seven K-line calls 241.970–248.013 ms, median 244.049 ms; one quote 488.063 ms. Sample size too small for p95/throughput claim; all schemas unqualified, no market-freshness validation.
- Oct 9 WebSocket: 15-second smoke yielded **no quote events**, so no push latency measurement.
- Oct 10 direct native ChatGPT STOCK RAZOR CN MCP observation: three serial cached-data tool calls ~4645, 2735 and 3062 ms *client-side wall time*; these include tool/connector overhead and scheduling, **not** upstream Tencent/TickFlow requests, and are not a representative p95 or stable SLA. Returned CN currentness remained `UNPROVEN`.

### Next benchmark contract (not yet executed)

1. Capture >=30 **authorized market-hours** REST observations per endpoint with source timestamps and independent monotonic timing; track p50/p95 and failures, rate limits.
2. Record each stage separately: provider timestamp → AWS receipt → normalization/cache → Radar decision → MCP response → phone push receipt. Use monotonic spans within a host and synchronized UTC timestamps across hosts; never subtract unsynchronized clocks without clock-offset evidence.
3. Separate **freshness** from **request duration**; a 244 ms response with stale bars is not live.
4. For WebSocket, capture market-hours event counts, heartbeat gaps, reconnects, stale thresholds, quota effects; zero events cannot establish latency.
5. Keep `SOURCE_ARBITER_ADMISSION=BLOCKED`, `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO` until data-quality and continuity gates independently pass.

No cloud deployment, provider requests or source/trading admission changes are part of this code-only PR.
