"""Synthetic offline market-to-notification latency audit safety contract."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.services.stock_radar_v2.notification_latency_audit import (
    audit_market_to_notification_traces,
)

BASE = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)


def trace(i=1, *, receipt=True):
    t = BASE + timedelta(seconds=i)
    result = {
        "source_runtime_id": "private-runtime-id",
        "source_sequence": i,
        "provider_timestamp_verified": True,
        "clock_sync_verified": True,
        "max_cross_host_clock_error_ms": 3.0,
        "provider_event_utc": t,
        "aws_ingest_utc": t + timedelta(milliseconds=100),
        "radar_complete_utc": t + timedelta(milliseconds=140),
        "notification_dispatch_utc": t + timedelta(milliseconds=150),
        "secret": "NEVER_PRINT_THIS",
    }
    if receipt:
        result["notification_receipt_utc"] = t + timedelta(milliseconds=300)
    return result


def test_30_unique_events_have_observational_percentiles_not_slo():
    result = audit_market_to_notification_traces([trace(i) for i in range(1, 31)])
    assert result["status"] == "OBSERVATIONAL_ONLY"
    assert result["accepted_unique_events"] == 30
    assert result["distributions"]["provider_to_receipt_ms"]["p95_ms"] == 300
    assert result["distributions"]["aws_to_radar_ms"]["p50_ms"] == 40
    assert result["latency_slo_qualified"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert "NEVER_PRINT_THIS" not in str(result)
    assert "private-runtime-id" not in str(result)


def test_fewer_than_30_never_publish_p95():
    result = audit_market_to_notification_traces([trace(i) for i in range(1, 4)])
    assert result["accepted_unique_events"] == 3
    assert result["distributions"]["provider_to_receipt_ms"]["p95_ms"] is None
    assert result["distributions"]["provider_to_receipt_ms"]["distribution_ready"] is False


def test_repeated_cache_event_is_not_a_second_sample():
    result = audit_market_to_notification_traces([trace(1), trace(1), trace(2)])
    assert result["accepted_unique_events"] == 2
    assert result["duplicate_sequences_skipped"] == 1


def test_invalid_first_observation_does_not_poison_valid_same_sequence():
    bad = trace(1)
    bad["clock_sync_verified"] = False
    result = audit_market_to_notification_traces([bad, trace(1)])
    assert result["accepted_unique_events"] == 1
    assert result["invalid_or_unqualified_skipped"] == 1
    assert result["duplicate_sequences_skipped"] == 0


def test_missing_phone_receipt_is_not_end_to_end():
    result = audit_market_to_notification_traces(
        [trace(i, receipt=i % 2 == 0) for i in range(1, 31)])
    assert result["accepted_unique_events"] == 30
    assert result["missing_receipt_events"] == 15
    assert result["distributions"]["aws_to_radar_ms"]["distribution_ready"] is True
    assert result["distributions"]["provider_to_receipt_ms"]["sample_count"] == 15
    assert result["distributions"]["provider_to_receipt_ms"]["p95_ms"] is None


def test_bad_clocks_provenance_and_nonmonotonic_spans_rejected():
    bad_clock = trace(1)
    bad_clock["max_cross_host_clock_error_ms"] = 99
    bad_provenance = trace(2)
    bad_provenance["provider_timestamp_verified"] = False
    reversed_time = trace(3)
    reversed_time["radar_complete_utc"] = BASE - timedelta(seconds=5)
    naive = trace(4)
    naive["aws_ingest_utc"] = BASE.replace(tzinfo=None)
    fake_receipt = trace(5)
    fake_receipt["notification_receipt_utc"] = "not a datetime"
    result = audit_market_to_notification_traces(
        [bad_clock, bad_provenance, reversed_time, naive, fake_receipt])
    assert result["accepted_unique_events"] == 0
    assert result["invalid_or_unqualified_skipped"] == 5
    assert result["data_qualification"] == "NOT_VERIFIED"


def test_input_bounds_fail_closed():
    assert audit_market_to_notification_traces([], min_samples=1)["status"] == "BLOCKED"
    assert audit_market_to_notification_traces([trace(i) for i in range(1001)])["status"] == "BLOCKED"
    assert audit_market_to_notification_traces([], min_samples=True)["status"] == "BLOCKED"


def test_no_network_provider_notification_or_trading_paths():
    source = (Path(__file__).resolve().parents[1] /
              "src/services/stock_radar_v2/notification_latency_audit.py").read_text(
                  encoding="utf-8")
    assert "import requests" not in source
    assert "import futu" not in source
    assert "send_notification(" not in source
    assert "place_order(" not in source
