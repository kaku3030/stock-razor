from datetime import date, datetime, timezone

from data_provider.futures_qualification import (
    FuturesSessionPhase,
    FuturesSessionPolicy,
    evaluate_futures_currentness,
)
from data_provider.live_feed_types import DeliveryMode, ProviderEvent, ProviderEventKind, SemanticStreamKey
from data_provider.provider_normalization import CanonicalProgress, compare_progress
from src.services.live_feed.qualification import FuturesLiveFeedQualificationHarness


NOW = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)  # Wednesday, 10:00 ET
KEY = SemanticStreamKey("yahoo_finance", "US_FUTURES", "GC", "KLINE", timeframe="5m", feed="vendor_continuous")
POLICY = FuturesSessionPolicy(holiday_calendar_verified=True)


def _event(*, timestamp=NOW, progress=1, delivery=DeliveryMode.UNKNOWN, key=KEY, **payload):
    identity = CanonicalProgress(timestamp, progress).encode()
    values = {
        "provider_timestamp": timestamp.isoformat(),
        "progress_identity": identity,
        "volume": 10,
        "instrument_root": "GC",
        "exchange": "COMEX",
        "volume_semantics": "contracts",
        "continuous_semantics": "vendor_continuous_candidate",
        "data_quality": "ok",
    }
    values.update(payload)
    return ProviderEvent(
        runtime_instance_id="r1",
        provider_id="yahoo_finance",
        controller_generation=0,
        observed_at_utc=NOW,
        observed_at_monotonic=1.0,
        event_kind=ProviderEventKind.DATA,
        semantic_stream_key=key,
        payload=values,
        provider_timestamp_raw=timestamp.isoformat(),
        delivery_mode=delivery,
        progress_identity_candidate=identity,
    )


def test_currentness_requires_active_verified_session_and_fresh_progress():
    decision = evaluate_futures_currentness(_event(), now_utc=NOW, session_policy=POLICY)
    assert decision.passed is True
    assert decision.reason == "CURRENTNESS_PROVEN_CANDIDATE"

    stale = evaluate_futures_currentness(
        _event(timestamp=datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)),
        now_utc=NOW,
        session_policy=POLICY,
    )
    assert stale.reason == "STALE_PROVIDER_OBSERVATION"


def test_break_weekend_and_holiday_are_expected_closed_not_current():
    for at, expected in (
        (datetime(2026, 10, 7, 21, 30, tzinfo=timezone.utc), FuturesSessionPhase.EXPECTED_SILENCE),
        (datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc), FuturesSessionPhase.CLOSED_SESSION),
    ):
        assert POLICY.phase(at) is expected
        assert evaluate_futures_currentness(_event(timestamp=at), now_utc=at, session_policy=POLICY).reason == "SESSION_CLOSED_OR_BREAK"

    holiday_policy = FuturesSessionPolicy(holidays=frozenset({date(2026, 10, 7)}), holiday_calendar_verified=True)
    assert evaluate_futures_currentness(_event(), now_utc=NOW, session_policy=holiday_policy).reason == "SESSION_CLOSED_OR_BREAK"


def test_missing_contract_metadata_and_future_timestamp_fail_closed():
    actual_key = SemanticStreamKey("yahoo_finance", "US_FUTURES", "GC", "KLINE", timeframe="5m", feed="actual_contract")
    assert evaluate_futures_currentness(_event(key=actual_key), now_utc=NOW, session_policy=POLICY).reason == "MISSING_CONTRACT_METADATA"
    future = _event(timestamp=datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc))
    assert evaluate_futures_currentness(future, now_utc=NOW, session_policy=POLICY).reason == "PROVIDER_TIMESTAMP_IN_FUTURE"
    assert evaluate_futures_currentness(
        _event(continuous_semantics="ambiguous"), now_utc=NOW, session_policy=POLICY
    ).reason == "AMBIGUOUS_ROLL_OR_FEED"


def test_yahoo_timestamp_and_synthetic_realtime_claim_cannot_promote_live():
    harness = FuturesLiveFeedQualificationHarness(runtime_instance_id="r1", session_policy=POLICY)
    harness.apply(ProviderEvent(
        runtime_instance_id="r1", provider_id="yahoo_finance", controller_generation=0,
        observed_at_utc=NOW, observed_at_monotonic=1.0, event_kind=ProviderEventKind.CONNECTED,
    ))
    harness.apply(_event(progress=1, delivery=DeliveryMode.REALTIME))
    harness.apply(_event(progress=2, delivery=DeliveryMode.REALTIME))
    snapshot = harness.snapshot(KEY)
    assert snapshot.lifecycle_state.value == "CONNECTED"
    assert snapshot.currentness.reason == "DELIVERY_MODE_NOT_REALTIME"
    assert harness.currentness_decision(KEY).passed is True


def test_unverified_calendar_and_missing_volume_are_unknown_or_blocked():
    unverified = evaluate_futures_currentness(
        _event(), now_utc=NOW, session_policy=FuturesSessionPolicy()
    )
    assert unverified.reason == "SESSION_CALENDAR_UNVERIFIED"
    missing_volume = evaluate_futures_currentness(
        _event(volume=None), now_utc=NOW, session_policy=POLICY
    )
    assert missing_volume.reason == "MISSING_VOLUME"


def test_same_progress_disconnect_and_generation_rollover_do_not_restore_trust():
    harness = FuturesLiveFeedQualificationHarness(runtime_instance_id="r1", session_policy=POLICY)
    harness.apply(ProviderEvent(
        runtime_instance_id="r1", provider_id="yahoo_finance", controller_generation=0,
        observed_at_utc=NOW, observed_at_monotonic=1.0, event_kind=ProviderEventKind.CONNECTED,
    ))
    harness.apply(_event(progress=1))
    harness.apply(_event(progress=1))
    first = CanonicalProgress(NOW, 1)
    assert compare_progress(first, first) == 0
    assert harness.snapshot(KEY).lifecycle_state.value == "CONNECTED"
    harness.apply(ProviderEvent(
        runtime_instance_id="r1", provider_id="yahoo_finance", controller_generation=0,
        observed_at_utc=NOW, observed_at_monotonic=2.0, event_kind=ProviderEventKind.DISCONNECTED,
    ))
    assert harness.snapshot(KEY).lifecycle_state.value == "DISCONNECTED"
    harness.rollover_generation(1)
    assert harness.currentness_decision(KEY) is None
