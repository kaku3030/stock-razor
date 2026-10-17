"""Single fail-closed admission truth for downstream LiveFeed consumers."""
from __future__ import annotations
from dataclasses import dataclass
from data_provider.live_feed_types import LifecycleState
from src.services.live_feed.qualification import QualificationStatus, StreamQualification

@dataclass(frozen=True)
class QualifiedLiveFeedAdmission:
    admitted: bool
    reason: str
    evidence_scope: str
    provider_id: str
    symbol: str

def admit_qualified_livefeed(snapshot: StreamQualification) -> QualifiedLiveFeedAdmission:
    key = snapshot.semantic_stream_key
    scope = str(snapshot.evidence_scope or "").strip().upper()
    if scope in {"", "SYNTHETIC_ONLY"}:
        return QualifiedLiveFeedAdmission(False, "NON_RUNTIME_EVIDENCE_SCOPE", scope, key.provider_id, key.symbol)
    if snapshot.cloud_livefeed != "VERIFIED":
        return QualifiedLiveFeedAdmission(False, "CLOUD_LIVEFEED_NOT_VERIFIED", scope, key.provider_id, key.symbol)
    if snapshot.lifecycle_state is not LifecycleState.LIVE:
        return QualifiedLiveFeedAdmission(False, "LIFECYCLE_NOT_LIVE", scope, key.provider_id, key.symbol)
    if snapshot.currentness.status is not QualificationStatus.PROVEN:
        return QualifiedLiveFeedAdmission(False, "CURRENTNESS_NOT_PROVEN", scope, key.provider_id, key.symbol)
    if snapshot.continuity.status is not QualificationStatus.PROVEN:
        return QualifiedLiveFeedAdmission(False, "CONTINUITY_NOT_PROVEN", scope, key.provider_id, key.symbol)
    return QualifiedLiveFeedAdmission(True, "QUALIFIED_LIVEFEED", scope, key.provider_id, key.symbol)
