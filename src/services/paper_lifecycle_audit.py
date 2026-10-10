"""Pure consistency audit for one offline paper lifecycle chain.

The audit joins immutable TradePlan, lifecycle projection, and optional paper
review evidence. It never creates execution intent or changes admission gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .paper_trade_review import PaperReviewStatus, PaperTradeReview
from .trade_lifecycle import LifecycleDecision, TradeLifecycleSnapshot
from .trade_plan import TradePlan


class PaperLifecycleAuditStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class PaperLifecycleAudit:
    status: PaperLifecycleAuditStatus
    plan_id: str
    lifecycle_id: str
    reasons: tuple[str, ...]
    mutation_allowed: bool = False


def audit_paper_lifecycle(
    plan: TradePlan,
    lifecycle: TradeLifecycleSnapshot,
    review: PaperTradeReview | None = None,
) -> PaperLifecycleAudit:
    """Check that one plan, lifecycle projection, and review agree."""

    reasons: list[str] = []
    if lifecycle.plan_id != plan.plan_id:
        reasons.append("LIFECYCLE_PLAN_MISMATCH")
    if lifecycle.mutation_allowed:
        reasons.append("LIFECYCLE_MUTATION_ALLOWED")
    if review is not None and review.plan_id != plan.plan_id:
        reasons.append("REVIEW_PLAN_MISMATCH")

    if lifecycle.decision is LifecycleDecision.PLAN_PASS:
        if review is None:
            reasons.append("PLAN_PASS_REVIEW_MISSING")
        elif review.status is PaperReviewStatus.BLOCKED:
            reasons.append("PLAN_PASS_REVIEW_BLOCKED")
    elif review is not None and review.status is PaperReviewStatus.COMPLETED:
        reasons.append("COMPLETED_REVIEW_WITHOUT_PLAN_PASS")

    return PaperLifecycleAudit(
        status=(
            PaperLifecycleAuditStatus.PASS
            if not reasons
            else PaperLifecycleAuditStatus.BLOCKED
        ),
        plan_id=plan.plan_id,
        lifecycle_id=lifecycle.lifecycle_id,
        reasons=tuple(reasons),
    )
