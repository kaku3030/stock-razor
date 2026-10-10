"""Fail-closed readiness assessment for a read-only Shadow stream."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .paper_replay_report import PaperReplayReport


class ShadowReadiness(StrEnum):
    NOT_READY = "NOT_READY"
    READY_READ_ONLY_SHADOW = "READY_READ_ONLY_SHADOW"


@dataclass(frozen=True)
class ShadowReadinessResult:
    status: ShadowReadiness
    reasons: tuple[str, ...]
    radar_admission: str = "BLOCKED"
    source_arbiter_admission: str = "BLOCKED"
    paper_auto_ready: bool = False
    live_trade: str = "NO"


def assess_read_only_shadow_readiness(
    report: PaperReplayReport,
    *,
    replay_passed: bool,
    restart_reconciliation_passed: bool,
    failure_injection_passed: bool,
    non_trade_reason_coverage_passed: bool,
    audit_integrity_passed: bool,
) -> ShadowReadinessResult:
    """Return a status only; this function cannot change runtime admission."""

    reasons: list[str] = []
    if report.lifecycle_count == 0:
        reasons.append("NO_REPLAY_LIFECYCLE")
    if report.completed_review_count == 0:
        reasons.append("NO_COMPLETED_PAPER_REVIEW")
    checks = (
        (replay_passed, "REPLAY_NOT_PASSED"),
        (restart_reconciliation_passed, "RESTART_RECONCILIATION_NOT_PASSED"),
        (failure_injection_passed, "FAILURE_INJECTION_NOT_PASSED"),
        (non_trade_reason_coverage_passed, "NON_TRADE_REASON_COVERAGE_NOT_PASSED"),
        (audit_integrity_passed, "AUDIT_INTEGRITY_NOT_PASSED"),
    )
    reasons.extend(reason for passed, reason in checks if passed is not True)
    status = (
        ShadowReadiness.READY_READ_ONLY_SHADOW
        if not reasons
        else ShadowReadiness.NOT_READY
    )
    return ShadowReadinessResult(status=status, reasons=tuple(reasons))
