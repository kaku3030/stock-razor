from datetime import datetime, timezone

from data_provider.futures_qualification import FuturesSessionPolicy
from data_provider.live_feed_types import DeliveryMode, LifecycleState, ProviderEvent, ProviderEventKind, SemanticStreamKey
from data_provider.provider_normalization import CanonicalProgress
from src.services.live_feed.qualification import (
    FuturesLiveFeedQualificationHarness,
    QualificationFact,
    QualificationStatus,
    StreamQualification,
)
from src.services.stock_radar_v2.futures_admission import admit_futures_to_radar
from data_provider.futures_runtime_observation import FuturesRuntimeObserver


NOW = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
KEY = SemanticStreamKey("yahoo_finance", "US_FUTURES", "GC", "KLINE", timeframe="5m", feed="vendor_continuous")


def _event(ts=NOW, sequence=1, *, observed=NOW, delivery=DeliveryMode.UNKNOWN, generation=0, **payload):
    identity = CanonicalProgress(ts, sequence).encode()
    values = {
        "provider_timestamp": ts.isoformat(),
        "progress_identity": identity,
        "volume": 10,
        "instrument_root": "GC",
        "exchange": "COMEX",
        "volume_semantics": "contracts",
        "continuous_semantics": "vendor_continuous_candidate",
    }
    values.update(payload)
    return ProviderEvent(
        runtime_instance_id="r1", provider_id="yahoo_finance", controller_generation=generation,
        observed_at_utc=observed, observed_at_monotonic=1.0, event_kind=ProviderEventKind.DATA,
        semantic_stream_key=KEY, payload=values, provider_timestamp_raw=ts.isoformat(),
        delivery_mode=delivery, progress_identity_candidate=identity,
    )


def test_observer_records_timestamps_progress_scope_and_vendor_identity():
    observer = FuturesRuntimeObserver(runtime_instance_id="r1", session_policy=FuturesSessionPolicy(holiday_calendar_verified=True))
    observation = observer.observe_event(_event(vendor_symbol="GC=F"))
    assert observation.evidence_scope == "RUNTIME_OBSERVATION"
    assert observation.provider_timestamp == NOW
    assert observation.age_seconds == 0
    assert observation.progress_identity
    assert observation.contract_identity == "GC=F"
    assert observation.feed_semantics == "vendor_continuous_candidate"
    assert observation.delivery_mode == "UNKNOWN"
    assert observation.qualification_status == "BLOCKED"


def test_observer_records_progress_gap_and_non_progress_without_promoting():
    observer = FuturesRuntimeObserver(runtime_instance_id="r1", session_policy=FuturesSessionPolicy(holiday_calendar_verified=True))
    observer.observe_event(_event(ts=datetime(2026, 10, 7, 13, 45, tzinfo=timezone.utc), sequence=1))
    gap = observer.observe_event(_event(ts=NOW, sequence=2))
    duplicate = observer.observe_event(_event(ts=NOW, sequence=2))
    assert gap.gap_status == "GAP"
    assert gap.continuity_status == "PROVEN"
    assert duplicate.continuity_reason == "NO_STRICTLY_LATER_PROGRESS"
    assert duplicate.qualification_status == "BLOCKED"


def test_observer_records_error_recovery_and_generation_rollover():
    observer = FuturesRuntimeObserver(runtime_instance_id="r1", session_policy=FuturesSessionPolicy())
    assert observer.record_transport(ProviderEventKind.ERROR, observed_at_utc=NOW, error="TimeoutError").transport_transition == "ERROR"
    assert observer.record_transport(ProviderEventKind.CONNECTED, observed_at_utc=NOW).transport_transition == "RECOVERED"
    rollover = observer.rollover_generation(1, observed_at_utc=NOW)
    assert rollover.transport_transition == "GENERATION_ROLLOVER"
    assert rollover.generation == 1


def test_observer_source_errors_are_blocked_and_sample_is_repeatable():
    observer = FuturesRuntimeObserver(runtime_instance_id="r1", session_policy=FuturesSessionPolicy())

    def failing(*_args, **_kwargs):
        raise TimeoutError("source unavailable")

    record = observer.sample(failing, "GC", "5m", observed_at_utc=NOW)[0]
    assert record.transport_transition == "ERROR"
    assert record.qualification_status == "BLOCKED"
    assert record.error == "TimeoutError"


def test_yahoo_freshness_cannot_bypass_radar_admission():
    event = _event(delivery=DeliveryMode.REALTIME)
    harness = FuturesLiveFeedQualificationHarness(
        runtime_instance_id="r1", session_policy=FuturesSessionPolicy(holiday_calendar_verified=True)
    )
    harness.apply(event)
    decision = admit_futures_to_radar(event, harness.snapshot(KEY))
    assert decision.accepted is False
    assert decision.reason == "LIVEFEED_NOT_QUALIFIED"


def test_radar_admission_rejects_identity_and_unqualified_continuity():
    harness = FuturesLiveFeedQualificationHarness(
        runtime_instance_id="r1", session_policy=FuturesSessionPolicy(holiday_calendar_verified=True)
    )
    harness.apply(ProviderEvent(
        runtime_instance_id="r1", provider_id="yahoo_finance", controller_generation=0,
        observed_at_utc=NOW, observed_at_monotonic=1, event_kind=ProviderEventKind.CONNECTED,
    ))
    harness.apply(_event(sequence=1))
    decision = admit_futures_to_radar(_event(sequence=2), harness.snapshot(KEY))
    assert decision.accepted is False
    assert decision.reason == "DELIVERY_MODE_NOT_REALTIME"


def test_radar_admission_cannot_be_bypassed_by_forged_live_snapshot():
    forged = StreamQualification(
        semantic_stream_key=KEY,
        lifecycle_state=LifecycleState.LIVE,
        provider_health=QualificationFact(QualificationStatus.PROVEN),
        last_bar_ts=QualificationFact(QualificationStatus.PROVEN),
        currentness=QualificationFact(QualificationStatus.PROVEN),
        continuity=QualificationFact(QualificationStatus.PROVEN),
        subscription_usage=QualificationFact(QualificationStatus.UNKNOWN),
    )
    decision = admit_futures_to_radar(_event(delivery=DeliveryMode.UNKNOWN), forged)
    assert decision.accepted is False
    assert decision.reason == "DELIVERY_MODE_NOT_REALTIME"
