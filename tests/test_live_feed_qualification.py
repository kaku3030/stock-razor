from datetime import datetime, timezone

from data_provider.live_feed_types import (
    DeliveryMode,
    LifecycleState,
    ProviderEvent,
    ProviderEventKind,
    SemanticStreamKey,
)
from data_provider.provider_normalization import CanonicalProgress
from src.services.live_feed.qualification import QualificationStatus, SyntheticLiveFeedQualificationHarness


NOW = datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)
KEY_A = SemanticStreamKey("synthetic", "US", "A", "BAR", timeframe="1m")
KEY_B = SemanticStreamKey("synthetic", "US", "B", "BAR", timeframe="1m")


def event(kind, key=None, *, generation=0, progress=None, timestamp="2026-10-03T01:00:00+00:00", phase=None):
    payload = {"provider_timestamp": timestamp, "data_quality": "ok"}
    if progress is not None:
        progress = CanonicalProgress(datetime.fromisoformat(timestamp), int(progress)).encode()
        payload["progress_identity"] = progress
    if phase is not None:
        payload["phase"] = phase
    return ProviderEvent(
        runtime_instance_id="r1",
        provider_id="synthetic",
        controller_generation=generation,
        observed_at_utc=NOW,
        observed_at_monotonic=1.0,
        event_kind=kind,
        semantic_stream_key=key,
        delivery_mode=DeliveryMode.REALTIME,
        payload=payload,
        progress_identity_candidate=progress,
    )


def test_connected_ack_and_seed_never_promote_to_live():
    h = SyntheticLiveFeedQualificationHarness(runtime_instance_id="r1", provider_id="synthetic")
    h.apply(event(ProviderEventKind.CONNECTED))
    h.apply(event(ProviderEventKind.SUBSCRIPTION_RESULT, KEY_A))
    h.apply(event(ProviderEventKind.DATA, KEY_A, progress="1", phase="SEED"))
    snap = h.snapshot(KEY_A)
    assert snap.lifecycle_state is LifecycleState.CONNECTED
    assert snap.continuity.status is QualificationStatus.UNKNOWN
    assert "SUBSCRIPTION_ACK_ADMINISTRATIVE_ONLY" in snap.findings


def test_currentness_and_continuity_are_per_symbol_and_can_promote_only_after_two_progresses():
    h = SyntheticLiveFeedQualificationHarness(runtime_instance_id="r1", provider_id="synthetic")
    h.apply(event(ProviderEventKind.CONNECTED))
    h.apply(event(ProviderEventKind.DATA, KEY_A, progress="1"))
    h.apply(event(ProviderEventKind.DATA, KEY_B, progress="1"))
    assert h.snapshot(KEY_A).lifecycle_state is LifecycleState.CONNECTED
    assert h.snapshot(KEY_B).lifecycle_state is LifecycleState.CONNECTED
    h.apply(event(ProviderEventKind.DATA, KEY_A, progress="2", timestamp="2026-10-03T01:00:00+00:00"))
    assert h.snapshot(KEY_A).lifecycle_state is LifecycleState.LIVE
    assert h.snapshot(KEY_B).lifecycle_state is LifecycleState.CONNECTED


def test_stale_duplicate_disconnect_and_old_generation_cannot_restore_or_extend_trust():
    h = SyntheticLiveFeedQualificationHarness(runtime_instance_id="r1", provider_id="synthetic")
    h.apply(event(ProviderEventKind.CONNECTED))
    h.apply(event(ProviderEventKind.DATA, KEY_A, progress="1"))
    h.apply(event(ProviderEventKind.DATA, KEY_A, progress="2", timestamp="2026-10-03T01:00:00+00:00"))
    assert h.snapshot(KEY_A).lifecycle_state is LifecycleState.LIVE
    h.apply(event(ProviderEventKind.DATA, KEY_A, progress="2", timestamp="2026-10-03T01:00:00+00:00"))
    assert h.snapshot(KEY_A).lifecycle_state is LifecycleState.CONNECTED
    assert "NO_PROGRESS_DUPLICATE_OR_OLD" in h.snapshot(KEY_A).findings
    h.apply(event(ProviderEventKind.DATA, KEY_A, progress="2", timestamp="2026-10-03T00:55:00+00:00"))
    assert h.snapshot(KEY_A).lifecycle_state is LifecycleState.CONNECTED
    h.apply(event(ProviderEventKind.DISCONNECTED))
    assert h.snapshot(KEY_A).lifecycle_state is LifecycleState.DISCONNECTED
    h.apply(event(ProviderEventKind.DATA, KEY_A, generation=0, progress="3"))
    assert h.snapshot(KEY_A).lifecycle_state is LifecycleState.DISCONNECTED


def test_rollover_clears_old_timestamp_ack_and_live_trust():
    h = SyntheticLiveFeedQualificationHarness(runtime_instance_id="r1", provider_id="synthetic")
    h.apply(event(ProviderEventKind.CONNECTED))
    h.apply(event(ProviderEventKind.DATA, KEY_A, progress="1"))
    h.apply(event(ProviderEventKind.DATA, KEY_A, progress="2", timestamp="2026-10-03T01:00:00+00:00"))
    h.rollover_generation(1)
    snap = h.snapshot(KEY_A)
    assert snap.lifecycle_state is LifecycleState.DISCONNECTED
    assert snap.last_bar_ts.status is QualificationStatus.UNKNOWN
    assert snap.subscription_usage.status is QualificationStatus.UNKNOWN
    h.apply(event(ProviderEventKind.CONNECTED, generation=1))
    h.apply(event(ProviderEventKind.DATA, KEY_A, generation=1, progress="2"))
    assert h.snapshot(KEY_A).lifecycle_state is LifecycleState.CONNECTED


def test_output_labels_synthetic_evidence_and_unknown_external_facts():
    snap = SyntheticLiveFeedQualificationHarness(runtime_instance_id="r1", provider_id="synthetic").snapshot(KEY_A)
    assert snap.evidence_scope == "SYNTHETIC_ONLY"
    assert snap.cloud_livefeed == "NOT_VERIFIED"
    assert snap.provider_health.status is QualificationStatus.UNKNOWN
    assert snap.subscription_usage.status is QualificationStatus.UNKNOWN
