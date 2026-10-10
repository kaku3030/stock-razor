# Offline provider-event → phone-notification latency audit V0.1

This research helper adds a **pure, local offline** stage-timing audit for STOCK RAZOR's future cloud-to-phone notification chain. It does not read or send any real market data, call providers, run AWS commands, send a push, or authorize trades.

## Required evidence

Each independently collected event must include a unique `(source_runtime_id, source_sequence)` pair and five stage timestamps:

1. `provider_event_utc`: **verified original provider/market event timestamp**, not the time a cached JSON file was read.
2. `aws_ingest_utc`: AWS receipt.
3. `radar_complete_utc`: completed Radar decision.
4. `notification_dispatch_utc`: notification sent by the gateway.
5. `notification_receipt_utc`: **actual device acknowledgement**, if available. A gateway HTTP 200 or enqueue acknowledgement is not device delivery.

All stage timestamps must be timezone-aware `datetime` values. A caller must independently prove `provider_timestamp_verified=True`, `clock_sync_verified=True`, and supply bounded `max_cross_host_clock_error_ms <= 10`. These are caller attestations, not proof from this helper. A negative/invalid chain, stale/delayed >120-second chain, unverified source, unsynchronized clock or duplicate source sequence is excluded. Unknown phone receipt is not silently inferred from dispatch.

The output contains **only aggregates**: accepted distinct events, rejected/duplicate counts, missing device receipts, and p50/p95/max stage spans. The audit will not report percentiles for fewer than **30 unique qualifying events per span**. Thirty samples are a minimum for descriptive reporting, **not** an adequate long-term p95 SLO proof.

The module returns `status=OBSERVATIONAL_ONLY`, `latency_slo_qualified=false`, `data_qualification=NOT_VERIFIED`, `radar_admission=BLOCKED`, and `live_trade=false` regardless of how fast synthetic or future observed events appear. A fast but stale source is not real-time.

## Existing timing must not be conflated

- Oct 9 TickFlow AWS Premium REST K-line ~244ms median (7 requests, no full-market freshness or schema qualification).
- OpenD callback metric ~67ms (provider-side reported processing metric, not phone latency).
- Cloud local cache reads sub-millisecond to tens of milliseconds (not provider request duration).
- Native ChatGPT MCP call wall time ~2–5 seconds (includes connector/tool overhead; does not prove Radar event-to-phone delay).
- Existing `CanonicalExportLatencyLedger` measures canonical export → Radar for distinct export sequences, **not** provider → device.

## Next independent acceptance work

Capture **real** uniquely correlated provider events, AWS ingestion, Radar completion, notification dispatch and device receipt while markets are open, with independently verified source lineage and clock offsets. Measure p50/p95 and failure rates across multiple sessions and provider fallback paths. Never turn on live trade or Radar admission from timing alone.

No AWS deploy, paid data request, subscription mutation or notification send is part of this PR.
