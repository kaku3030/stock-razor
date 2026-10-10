from dataclasses import replace
from data_provider.live_feed_types import LifecycleState, SemanticStreamKey
from src.services.live_feed.qualification import QualificationFact, QualificationStatus, StreamQualification
from src.services.stock_radar_v2.livefeed_admission import admit_livefeed_for_radar

KEY = SemanticStreamKey("moomoo_opend", "US", "AMD", "KLINE", "1m")

def snapshot(**changes):
    base = StreamQualification(
        semantic_stream_key=KEY,
        lifecycle_state=LifecycleState.LIVE,
        provider_health=QualificationFact(QualificationStatus.PROVEN),
        last_bar_ts=QualificationFact(QualificationStatus.PROVEN),
        currentness=QualificationFact(QualificationStatus.PROVEN),
        continuity=QualificationFact(QualificationStatus.PROVEN),
        subscription_usage=QualificationFact(QualificationStatus.UNKNOWN),
        evidence_scope="RUNTIME_PROVIDER",
        cloud_livefeed="VERIFIED",
    )
    return replace(base, **changes)

def test_synthetic_evidence_is_never_admitted():
    result = admit_livefeed_for_radar(snapshot(evidence_scope="SYNTHETIC_ONLY"))
    assert result.admitted is False
    assert result.reason == "NON_RUNTIME_EVIDENCE_SCOPE"

def test_unknown_currentness_is_never_admitted():
    result = admit_livefeed_for_radar(snapshot(currentness=QualificationFact(QualificationStatus.UNKNOWN)))
    assert result.admitted is False
    assert result.reason == "CURRENTNESS_NOT_PROVEN"

def test_unverified_cloud_livefeed_is_never_admitted():
    result = admit_livefeed_for_radar(snapshot(cloud_livefeed="NOT_VERIFIED"))
    assert result.admitted is False
    assert result.reason == "CLOUD_LIVEFEED_NOT_VERIFIED"

def test_only_runtime_verified_live_current_continuous_snapshot_is_admitted():
    result = admit_livefeed_for_radar(snapshot())
    assert result.admitted is True
    assert result.reason == "QUALIFIED_LIVEFEED"


def test_live_lifecycle_cannot_override_blocked_continuity():
    result = admit_livefeed_for_radar(
        snapshot(continuity=QualificationFact(QualificationStatus.BLOCKED))
    )
    assert result.admitted is False
    assert result.reason == "CONTINUITY_NOT_PROVEN"
