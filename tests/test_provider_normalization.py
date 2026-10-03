from datetime import datetime, timezone

from data_provider.live_feed_types import DeliveryMode, ProviderEventKind, SemanticStreamKey
from data_provider.provider_normalization import (
    CanonicalProgress,
    compare_progress,
    normalize_eastmoney_quote,
    normalize_opend_callback,
)


NOW = datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)
KEY = SemanticStreamKey("moomoo_opend", "US", "AAPL", "BAR", timeframe="1m")


def test_progress_is_utc_and_requires_sequence_for_same_timestamp():
    first = CanonicalProgress(datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc), 7)
    same_timestamp_without_sequence = CanonicalProgress(first.provider_timestamp_utc)
    later = CanonicalProgress(first.provider_timestamp_utc, 8)
    assert compare_progress(first, same_timestamp_without_sequence) == 0
    assert compare_progress(first, later) == 1
    assert "2026-10-03T10:00:00Z" in first.encode()


def test_progress_does_not_use_ordinary_string_dictionary_order():
    first = CanonicalProgress(datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc), 2)
    later = CanonicalProgress(datetime(2026, 10, 3, 1, 0, 1, tzinfo=timezone.utc), 10)
    assert compare_progress(first, later) == 1


def test_opend_normalization_preserves_unknown_entitlement_and_phase():
    event = normalize_opend_callback(
        raw={
            "provider_timestamp": "2026-10-03T01:00:00+00:00",
            "phase": "SEED",
            "delivery_mode": "UNKNOWN",
            "sequence": 1,
        },
        runtime_instance_id="r1",
        controller_generation=0,
        observed_at_utc=NOW,
        semantic_stream_key=KEY,
    )
    assert event.event_kind is ProviderEventKind.DATA
    assert event.delivery_mode is DeliveryMode.UNKNOWN
    assert event.payload["phase"] == "SEED"
    assert event.payload["entitlement"] == "UNKNOWN"
    assert event.progress_identity_candidate is not None


def test_eastmoney_normalization_does_not_promote_api_row_to_realtime():
    event = normalize_eastmoney_quote(
        raw={"timestamp": "2026-10-03T01:00:00+00:00", "sequence": 1},
        runtime_instance_id="r1",
        controller_generation=0,
        observed_at_utc=NOW,
        semantic_stream_key=SemanticStreamKey("eastmoney", "CN", "600519", "BAR", timeframe="1d"),
    )
    assert event.delivery_mode is DeliveryMode.UNKNOWN
    assert event.payload["entitlement"] == "UNKNOWN"
