"""Synthetic, no-network checks for a cloud Paper evidence *report*, not orders."""
from dataclasses import replace

from src.services.paper_cloud_evidence_review import (
    CloudPaperEvidenceStatus,
    CloudPaperObservation,
    assess_cloud_paper_evidence,
)
from src.services.paper_shadow_readiness import ShadowReadiness, ShadowReadinessResult
from src.services.sim_account_continuity import SimContinuityReview


def _shadow():
    return ShadowReadinessResult(ShadowReadiness.READY_READ_ONLY_SHADOW, ())


def _sim():
    return SimContinuityReview(
        "MATCHED_FOR_REVIEW", "INDEPENDENT_FILLS_STILL_UNKNOWN",
        position_count=4, same_account_id=True, same_positions=True,
    )


def _verified_cloud():
    return CloudPaperObservation(
        **{name: True for name in CloudPaperObservation.__dataclass_fields__}
    )


def test_current_missing_cloud_market_and_sim_fill_evidence_blocks():
    inputs = replace(
        _verified_cloud(),
        quote_sequence_advanced=None,
        timestamp_freshness_verified=None,
        bars_15m_60m_closed_verified=None,
        k5m_volume_turnover_parity_verified=False,
        independent_sim_fill_receipt_verified=None,
    )
    result = assess_cloud_paper_evidence(
        offline_shadow=_shadow(), sim_continuity=_sim(), cloud=inputs,
    )
    assert result.status is CloudPaperEvidenceStatus.BLOCKED
    assert result.reasons == (
        "QUOTE_SEQUENCE_ADVANCED_UNKNOWN",
        "TIMESTAMP_FRESHNESS_VERIFIED_UNKNOWN",
        "BARS_15M_60M_CLOSED_VERIFIED_UNKNOWN",
        "K5M_VOLUME_TURNOVER_PARITY_VERIFIED_FAILED",
        "INDEPENDENT_SIM_FILL_RECEIPT_VERIFIED_UNKNOWN",
    )
    assert result.paper_auto_ready is False
    assert result.broker_mutation_allowed is False
    assert result.live_trade == "NO"
    assert result.trade_execution == "NO"


def test_all_synthetic_pass_is_not_execution_authorization():
    result = assess_cloud_paper_evidence(
        offline_shadow=_shadow(), sim_continuity=_sim(),
        cloud=_verified_cloud(),
    )
    assert result.status is CloudPaperEvidenceStatus.EVIDENCE_READY_FOR_SUPERVISED_REVIEW
    assert result.reasons == ()
    assert result.paper_auto_ready is False
    assert result.broker_mutation_allowed is False
    assert result.radar_admission == "BLOCKED"
    assert result.source_arbiter_admission == "BLOCKED"
    assert result.live_trade == "NO"
    assert result.trade_execution == "NO"


def test_missing_wrong_type_or_truthy_values_cannot_fake_evidence():
    for bogus in (None, True, 1, "true", ["PASS"]):
        cloud = replace(_verified_cloud(), quote_sequence_advanced=bogus)
        result = assess_cloud_paper_evidence(
            offline_shadow=_shadow(), sim_continuity=_sim(), cloud=cloud,
        )
        if bogus is True:
            assert result.status is CloudPaperEvidenceStatus.EVIDENCE_READY_FOR_SUPERVISED_REVIEW
        else:
            assert result.status is CloudPaperEvidenceStatus.BLOCKED
            assert any("QUOTE_SEQUENCE_ADVANCED_" in r for r in result.reasons)


def test_missing_and_untrusted_scopes_always_block():
    missing = assess_cloud_paper_evidence(
        offline_shadow=None, sim_continuity=None, cloud=None,
    )
    assert missing.status is CloudPaperEvidenceStatus.BLOCKED
    assert "OFFLINE_SHADOW_READINESS_NOT_VERIFIED" in missing.reasons
    assert "APPROVED_SIM_ACCOUNT_CONTINUITY_NOT_VERIFIED" in missing.reasons
    assert "OPEND_REVISION_ALIGNED_UNKNOWN" in missing.reasons

    for sim in (None, replace(_sim(), status="BLOCKED"),
                replace(_sim(), broker_mutation_allowed=True)):
        result = assess_cloud_paper_evidence(
            offline_shadow=_shadow(), sim_continuity=sim, cloud=_verified_cloud(),
        )
        assert result.status is CloudPaperEvidenceStatus.BLOCKED
        assert "APPROVED_SIM_ACCOUNT_CONTINUITY_NOT_VERIFIED" in result.reasons

    bad_shadow = replace(_shadow(), radar_admission="OPEN")
    result = assess_cloud_paper_evidence(
        offline_shadow=bad_shadow, sim_continuity=_sim(), cloud=_verified_cloud(),
    )
    assert result.status is CloudPaperEvidenceStatus.BLOCKED


def test_private_values_do_not_enter_fixed_reason_strings():
    sim = replace(
        _sim(), status="BLOCKED",
        reason="PRIVATE_ACCOUNT_ID=999-SECRET-POSITIONS",
    )
    result = assess_cloud_paper_evidence(
        offline_shadow=_shadow(), sim_continuity=sim, cloud=_verified_cloud(),
    )
    assert "PRIVATE_ACCOUNT_ID" not in repr(result)
    assert "999-SECRET-POSITIONS" not in repr(result)
    assert result.reasons == ("APPROVED_SIM_ACCOUNT_CONTINUITY_NOT_VERIFIED",)
