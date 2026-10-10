from decimal import Decimal

from src.services.paper_replay_report import PaperReplayReport
from src.services.paper_shadow_readiness import (
    ShadowReadiness,
    assess_read_only_shadow_readiness,
)


def report(**changes):
    values = dict(
        report_id="replay-1",
        lifecycle_count=1,
        wait_count=0,
        no_trade_count=0,
        entry_blocked_count=0,
        plan_pass_count=1,
        completed_review_count=1,
        blocked_review_count=0,
        realized_pnl_total=Decimal("1"),
        realized_r_total=Decimal("0.1"),
        blocked_reasons=(),
        non_trade_reason_coverage_passed=True,
    )
    values.update(changes)
    return PaperReplayReport(**values)


def test_shadow_readiness_requires_all_evidence_and_keeps_gates_closed():
    result = assess_read_only_shadow_readiness(
        report(),
        replay_passed=True,
        restart_reconciliation_passed=True,
        failure_injection_passed=True,
        non_trade_reason_coverage_passed=True,
        audit_integrity_passed=True,
    )
    assert result.status is ShadowReadiness.READY_READ_ONLY_SHADOW
    assert result.reasons == ()
    assert result.radar_admission == "BLOCKED"
    assert result.paper_auto_ready is False
    assert result.live_trade == "NO"


def test_shadow_readiness_fails_closed_with_explicit_missing_evidence():
    result = assess_read_only_shadow_readiness(
        report(lifecycle_count=0, completed_review_count=0),
        replay_passed=True,
        restart_reconciliation_passed=False,
        failure_injection_passed=False,
        non_trade_reason_coverage_passed=False,
        audit_integrity_passed=False,
    )
    assert result.status is ShadowReadiness.NOT_READY
    assert result.reasons == (
        "NO_REPLAY_LIFECYCLE",
        "NO_COMPLETED_PAPER_REVIEW",
        "RESTART_RECONCILIATION_NOT_PASSED",
        "FAILURE_INJECTION_NOT_PASSED",
        "NON_TRADE_REASON_COVERAGE_NOT_PASSED",
        "AUDIT_INTEGRITY_NOT_PASSED",
    )


def test_shadow_readiness_does_not_trust_external_coverage_flag_alone():
    result = assess_read_only_shadow_readiness(
        report(non_trade_reason_coverage_passed=False),
        replay_passed=True,
        restart_reconciliation_passed=True,
        failure_injection_passed=True,
        non_trade_reason_coverage_passed=True,
        audit_integrity_passed=True,
    )
    assert result.status is ShadowReadiness.NOT_READY
    assert result.reasons == ("REPORT_NON_TRADE_REASON_COVERAGE_NOT_PASSED",)
