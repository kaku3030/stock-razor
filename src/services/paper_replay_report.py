"""Read-only aggregate report for deterministic paper replay evidence."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .paper_trade_review import PaperReviewStatus, PaperTradeReview
from .trade_lifecycle import LifecycleDecision, TradeLifecycleSnapshot


@dataclass(frozen=True)
class PaperReplayReport:
    report_id: str
    lifecycle_count: int
    wait_count: int
    no_trade_count: int
    entry_blocked_count: int
    plan_pass_count: int
    completed_review_count: int
    blocked_review_count: int
    realized_pnl_total: Decimal
    realized_r_total: Decimal
    blocked_reasons: tuple[str, ...]
    paper_auto_ready: bool = False
    non_trade_reasons: tuple[str, ...] = ()
    non_trade_reason_coverage_passed: bool = False
    radar_admission: str = "BLOCKED"
    source_arbiter_admission: str = "BLOCKED"
    live_trade: str = "NO"


def build_paper_replay_report(
    report_id: str,
    lifecycles: tuple[TradeLifecycleSnapshot, ...],
    reviews: tuple[PaperTradeReview, ...],
) -> PaperReplayReport:
    """Aggregate supplied replay evidence without persistence or side effects."""

    if not isinstance(report_id, str) or not report_id.strip():
        raise ValueError("report_id is required")
    lifecycle_counts = {
        decision: sum(1 for item in lifecycles if item.decision is decision)
        for decision in LifecycleDecision
    }
    completed = [item for item in reviews if item.status is PaperReviewStatus.COMPLETED]
    blocked = [item for item in reviews if item.status is PaperReviewStatus.BLOCKED]
    realized_pnl = sum((item.realized_pnl or Decimal("0") for item in completed), Decimal("0"))
    realized_r = sum((item.realized_r or Decimal("0") for item in completed), Decimal("0"))
    reasons = tuple(reason for item in blocked for reason in item.reasons)
    non_trade_decisions = {
        LifecycleDecision.WAIT,
        LifecycleDecision.NO_TRADE,
        LifecycleDecision.ENTRY_BLOCKED,
    }
    non_trade_items = [
        item for item in lifecycles if item.decision in non_trade_decisions
    ]
    non_trade_reasons = tuple(
        reason for item in non_trade_items for reason in item.reasons
    )
    non_trade_reason_coverage_passed = all(
        bool(item.reasons) for item in non_trade_items
    )
    return PaperReplayReport(
        report_id=report_id.strip(),
        lifecycle_count=len(lifecycles),
        wait_count=lifecycle_counts[LifecycleDecision.WAIT],
        no_trade_count=lifecycle_counts[LifecycleDecision.NO_TRADE],
        entry_blocked_count=lifecycle_counts[LifecycleDecision.ENTRY_BLOCKED],
        plan_pass_count=lifecycle_counts[LifecycleDecision.PLAN_PASS],
        completed_review_count=len(completed),
        blocked_review_count=len(blocked),
        realized_pnl_total=realized_pnl,
        realized_r_total=realized_r,
        blocked_reasons=reasons,
        non_trade_reasons=non_trade_reasons,
        non_trade_reason_coverage_passed=non_trade_reason_coverage_passed,
    )
