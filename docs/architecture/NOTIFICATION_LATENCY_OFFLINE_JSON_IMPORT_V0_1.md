# Offline JSON import for provider-to-device latency audit V0.1

The previously merged unique-event latency auditor accepts Python `datetime` objects. This adapter allows **already collected private local JSON traces** to be analyzed without deploying AWS code, making provider requests, sending push notifications, or sending the trace payload to a third party.

Run from the repository root:

```sh
python -m scripts.notification_latency_json_audit < private-traces.json
```

Input: one JSON **array** (at most 1,000 records, at most 2 MB). Each event has:

```json
{
  "source_runtime_id": "independently-identified-runtime",
  "source_sequence": 1,
  "provider_timestamp_verified": true,
  "clock_sync_verified": true,
  "max_cross_host_clock_error_ms": 3,
  "provider_event_utc": "2026-10-09T14:00:00Z",
  "aws_ingest_utc": "2026-10-09T14:00:00.100Z",
  "radar_complete_utc": "2026-10-09T14:00:00.140Z",
  "notification_dispatch_utc": "2026-10-09T14:00:00.150Z",
  "notification_receipt_utc": "2026-10-09T14:00:00.300Z",
  "device_receipt_verified": true
}
```

All timestamps require an explicit timezone. The phone receipt is **optional**; if supplied it requires independent device-side proof (`device_receipt_verified=true`). This importer **does not establish** that provider provenance, clock synchronization or device receipt assertions are true. They must be independently validated before any claims. The input schema is strictly field-whitelisted, unknown keys (including secrets, account IDs, ticker and raw event data) are not copied to output; only aggregate counters and p50/p95/max are printed. At least 30 unique qualifying events are needed for a descriptive percentile, **not** for an SLO guarantee.

Do not put raw API credentials in trace files. Prefer offline, locally controlled storage. JSON output is `OBSERVATIONAL_ONLY` with `data_qualification=NOT_VERIFIED`, `latency_slo_qualified=false`, `radar_admission=BLOCKED`, `live_trade=false`. No AWS deployment, paid provider requests or actual phone push sends occur in this PR.
