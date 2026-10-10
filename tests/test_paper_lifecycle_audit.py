"""Acceptance tests for the offline lifecycle consistency audit."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.services.execution_engine import Side
from src.services.paper_lifecycle_audit import (
    PaperLifecycleAuditStatus,
    audit_paper_lifecycle,
)
from src.services.paper_trade_review import (
    PaperReplayFill,
    PaperReviewStatus,
    review_completed_paper_trade,
)
from src.services.trade_lifecycle import (
    LifecycleDecision,
    LifecycleStage,
    TradeLifecycleSnapshot,
    project_trade_lifecycle,
)
from src.services.trade_plan import TradeDirection, TradeHorizon, TradePlan


NOW = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


def plan(**overrides):
    values = dict(
        plan_id="audit-plan",
        version="v0.2",
        symbol="AAPL",
        direction=TradeDirection.LONG,
        strategy="replay",
        horizon=TradeHorizon.INTRADAY,
        entry_low=Decimal("100"),
        entry_high=Decimal("101"),
        entry_ttl=NOW + timedelta(minutes=5),
        trigger_frame="5m",
        invalidation="invalidated",
        stop_price=Decimal("98"),
        target_price=Decimal("106"),
        quantity=Decimal("10"),
        risk_budget_r=Decimal("1"),
        estimated_cost=Decimal("0"),
        estimated_slippage=Decimal("0"),
        source="offline",
        quote_age_seconds=0,
        monitoring_status="PASS",
        protection_status="PASS",
    )
    values.update(overrides)
    return TradePlan(**values)


def completed_review(item):
    return review_completed_paper_trade(
        item,
        PaperReplayFill(Side.BUY, Decimal("10"), Decimal("100"), NOW),
        PaperReplayFill(
            Side.SELL, Decimal("10"), Decimal("104"), NOW + timedelta(minutes=20)
        ),
    )


def test_pass_requires_plan_pass_and_completed_matching_review():
    item = plan()
    lifecycle = project_trade_lifecycle(
        item, now=NOW, trigger_ready=True, execution_evidence_ready=True
    )
    review = completed_review(item)
    result = audit_paper_lifecycle(item, lifecycle, review)
    assert lifecycle.decision is LifecycleDecision.PLAN_PASS
    assert review.status is PaperReviewStatus.COMPLETED
    assert result.status is PaperLifecycleAuditStatus.PASS
    assert result.reasons == ()
    assert result.mutation_allowed is False


def test_plan_pass_without_review_is_blocked():
    item = plan()
    lifecycle = project_trade_lifecycle(
        item, now=NOW, trigger_ready=True, execution_evidence_ready=True
    )
    result = audit_paper_lifecycle(item, lifecycle)
    assert result.status is PaperLifecycleAuditStatus.BLOCKED
    assert result.reasons == ("PLAN_PASS_REVIEW_MISSING",)


def test_non_pass_with_completed_review_is_blocked():
    item = plan()
    lifecycle = project_trade_lifecycle(item, now=NOW, trigger_ready=False)
    result = audit_paper_lifecycle(item, lifecycle, completed_review(item))
    assert lifecycle.decision is LifecycleDecision.NO_TRADE
    assert result.status is PaperLifecycleAuditStatus.BLOCKED
    assert result.reasons == ("COMPLETED_REVIEW_WITHOUT_PLAN_PASS",)


def test_plan_and_review_mismatch_fail_closed():
    first = plan()
    second = plan(plan_id="other-plan")
    lifecycle = project_trade_lifecycle(
        first, now=NOW, trigger_ready=True, execution_evidence_ready=True
    )
    result = audit_paper_lifecycle(first, lifecycle, completed_review(second))
    assert result.status is PaperLifecycleAuditStatus.BLOCKED
    assert result.reasons == ("REVIEW_PLAN_MISMATCH",)
