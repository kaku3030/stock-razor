"""Offline JSON latency import must never leak raw traces or claim live delivery."""
import json
from datetime import datetime, timedelta, timezone

from scripts.notification_latency_json_audit import (
    MAX_INPUT_BYTES, audit_json_bytes,
)

BASE = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)


def row(seq=1, *, with_receipt=True):
    t = BASE + timedelta(seconds=seq)
    result = {
        "source_runtime_id": "private-source-identity",
        "source_sequence": seq,
        "provider_timestamp_verified": True,
        "clock_sync_verified": True,
        "max_cross_host_clock_error_ms": 2,
        "provider_event_utc": t.isoformat(),
        "aws_ingest_utc": (t + timedelta(milliseconds=90)).isoformat(),
        "radar_complete_utc": (t + timedelta(milliseconds=120)).isoformat(),
        "notification_dispatch_utc": (t + timedelta(milliseconds=150)).isoformat(),
        "account_number": "PRIVATE-ACCOUNT",
        "api_key": "SECRET-TOKEN",
        "ticker": "US.PRIVATE",
    }
    if with_receipt:
        result["notification_receipt_utc"] = (
            t + timedelta(milliseconds=220)).isoformat()
        result["device_receipt_verified"] = True
    return result


def audit(rows):
    return audit_json_bytes(json.dumps(rows).encode("utf-8"))


def test_realistic_synthetic_30_event_json_reports_aggregates_only():
    result = audit([row(i) for i in range(1, 31)])
    assert result["status"] == "OBSERVATIONAL_ONLY"
    assert result["accepted_unique_events"] == 30
    assert result["distributions"]["provider_to_receipt_ms"]["p95_ms"] == 220
    assert result["latency_slo_qualified"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    for secret in ("SECRET-TOKEN", "PRIVATE-ACCOUNT", "private-source-identity",
                   "US.PRIVATE"):
        assert secret not in str(result)


def test_repeated_cached_event_not_counted_twice():
    result = audit([row(1), row(1)])
    assert result["accepted_unique_events"] == 1
    assert result["duplicate_sequences_skipped"] == 1


def test_dispatch_only_not_phone_receipt():
    result = audit([row(i, with_receipt=False) for i in range(1, 31)])
    assert result["accepted_unique_events"] == 30
    assert result["missing_receipt_events"] == 30
    assert result["distributions"]["provider_to_receipt_ms"]["p95_ms"] is None


def test_receipt_without_device_attestation_is_rejected():
    x = row(1)
    x["device_receipt_verified"] = False
    result = audit([x])
    assert result["accepted_unique_events"] == 0
    assert result["invalid_or_unqualified_skipped"] == 1


def test_bad_input_and_oversized_input_fail_closed():
    for payload in (
        b"not json", b"{}", b"null", b"", b"[" + b"{}," * 1001 + b"{}]",
        b" " * (MAX_INPUT_BYTES + 1),
    ):
        result = audit_json_bytes(payload)
        assert result["status"] == "BLOCKED"
        assert result["provider_requests"] == 0
        assert result["notification_sends"] == 0
        assert result["live_trade"] is False


def test_naive_or_invalid_timestamps_cannot_be_measured():
    naive = row(1)
    naive["aws_ingest_utc"] = "2026-10-09T14:00:01"
    malformed = row(2)
    malformed["provider_event_utc"] = "invalid"
    result = audit([naive, malformed])
    assert result["accepted_unique_events"] == 0
    assert result["invalid_or_unqualified_skipped"] == 2


def test_z_suffix_is_supported_for_utc():
    x = row(1)
    x["provider_event_utc"] = x["provider_event_utc"].replace("+00:00", "Z")
    result = audit([x])
    assert result["accepted_unique_events"] == 1


def test_json_never_attests_provenance_itself():
    x = row(1)
    x["provider_timestamp_verified"] = False
    result = audit([x])
    assert result["accepted_unique_events"] == 0
    assert result["data_qualification"] == "NOT_VERIFIED"
