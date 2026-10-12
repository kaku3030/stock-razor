"""Read-only cloud Paper evidence rollup, never a broker or order admission.

The caller is responsible for independently attested, current observations.
This module does not connect to providers, issue orders, set environment gates,
or confer any execution capability. Even a complete synthetic input is only
eligible for supervised evidence review, never automatic Paper.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .paper_shadow_readiness import ShadowReadiness, ShadowReadinessResult
from .sim_account_continuity import SimContinuityReview


class CloudPaperEvidenceStatus(StrEnum):
    BLOCKED = "BLOCKED"
    EVIDENCE_READY_FOR_SUPERVISED_REVIEW = "EVIDENCE_READY_FOR_SUPERVISED_REVIEW"


@dataclass(frozen=True)
class CloudPaperObservation:
    """Externally verified booleans only; None means unverified, not a pass."""

    opend_revision_aligned: bool | None = None
    radar_revision_aligned: bool | None = None
    quote_rights_independently_verified: bool | None = None
    quote_sequence_advanced: bool | None = None
    timestamp_freshness_verified: bool | None = None
    bars_15m_60m_closed_verified: bool | None = None
    k5m_volume_turnover_parity_verified: bool | None = None
    old_sim_positions_quarantined: bool | None = None
    cloud_restart_recovery_verified: bool | None = None
    phone_notification_receipt_verified: bool | None = None
    independent_sim_fill_receipt_verified: bool | None = None


@dataclass(frozen=True)
class CloudPaperEvidenceReview:
    status: CloudPaperEvidenceStatus
    reasons: tuple[str, ...]
    paper_auto_ready: bool = False
    broker_mutation_allowed: bool = False
    source_arbiter_admission: str = "BLOCKED"
    radar_admission: str = "BLOCKED"
    live_trade: str = "NO"
    trade_execution: str = "NO"


_REQUIRED_OBSERVATIONS = (
    "opend_revision_aligned",
    "radar_revision_aligned",
    "quote_rights_independently_verified",
    "quote_sequence_advanced",
    "timestamp_freshness_verified",
    "bars_15m_60m_closed_verified",
    "k5m_volume_turnover_parity_verified",
    "old_sim_positions_quarantined",
    "cloud_restart_recovery_verified",
    "phone_notification_receipt_verified",
    "independent_sim_fill_receipt_verified",
)


def assess_cloud_paper_evidence(
    *,
    offline_shadow: ShadowReadinessResult | None,
    sim_continuity: SimContinuityReview | None,
    cloud: CloudPaperObservation | None,
) -> CloudPaperEvidenceReview:
    """Summarize P4/P5/P6 evidence without ever promoting Paper or trading.

    Results contain fixed reason codes only: no symbols, account IDs, provider
    diagnostics, position sizes, tokens or broker snapshots.
    """
    reasons: list[str] = []
    if (
        not isinstance(offline_shadow, ShadowReadinessResult)
        or offline_shadow.status is not ShadowReadiness.READY_READ_ONLY_SHADOW
        or offline_shadow.paper_auto_ready is not False
        or offline_shadow.radar_admission != "BLOCKED"
        or offline_shadow.source_arbiter_admission != "BLOCKED"
        or offline_shadow.live_trade != "NO"
    ):
        reasons.append("OFFLINE_SHADOW_READINESS_NOT_VERIFIED")

    if (
        not isinstance(sim_continuity, SimContinuityReview)
        or sim_continuity.status != "MATCHED_FOR_REVIEW"
        or sim_continuity.same_account_id is not True
        or sim_continuity.same_positions is not True
        or sim_continuity.paper_auto_ready is not False
        or sim_continuity.broker_mutation_allowed is not False
        or sim_continuity.live_trade is not False
        or sim_continuity.radar_admission != "BLOCKED"
    ):
        reasons.append("APPROVED_SIM_ACCOUNT_CONTINUITY_NOT_VERIFIED")

    for field in _REQUIRED_OBSERVATIONS:
        value = getattr(cloud, field) if isinstance(cloud, CloudPaperObservation) else None
        if value is True:
            continue
        suffix = "UNKNOWN" if value is None else "FAILED" if value is False else "INVALID"
        reasons.append(f"{field.upper()}_{suffix}")

    status = (
        CloudPaperEvidenceStatus.BLOCKED if reasons
        else CloudPaperEvidenceStatus.EVIDENCE_READY_FOR_SUPERVISED_REVIEW
    )
    return CloudPaperEvidenceReview(status=status, reasons=tuple(reasons))
