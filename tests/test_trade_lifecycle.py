from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.services.position_management import (
    PositionManagementAction,
    PositionManagementResult,
)
from src.services.trade_lifecycle import (
    LifecycleDecision,
    LifecycleStage,
    project_trade_lifecycle,
)
from src.services.trade_plan import TradeDirection, TradeHorizon, TradePlan


NOW = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


def plan(**changes):
    values = dict(
        plan_id="plan-1",
        version="trade-plan-v0.2",
        symbol="AAPL",
        direction=TradeDirection.LONG,
        strategy="breakout-retest",
        horizon=TradeHorizon.INTRADAY,
        entry_low=Decimal("100"),
        entry_high=Decimal("101"),
        entry_ttl=NOW + timedelta(minutes=5),
        trigger_frame="5m",
        invalidation="failed retest",
        stop_price=Decimal("98"),
        target_price=Decimal("106"),
        quantity=Decimal("1"),
        risk_budget_r=Decimal("1"),
        estimated_cost=Decimal("0.1"),
        estimated_slippage=Decimal("0.05"),
        source="opend-readonly",
        quote_age_seconds=2,
        monitoring_status="READY",
        protection_status="PLANNED_NOT_ACKED",
    )
    values.update(changes)
    return TradePlan(**values)


def test_plan_wait_is_distinguished_from_no_trade_and_blocked():
    wait = project_trade_lifecycle(plan(direction=TradeDirection.WAIT), now=NOW)
    no_trade = project_trade_lifecycle(plan(), now=NOW, trigger_ready=False)
    blocked = project_trade_lifecycle(plan(stop_price=None), now=NOW)
    assert wait.decision is LifecycleDecision.WAIT
    assert no_trade.decision is LifecycleDecision.NO_TRADE
    assert blocked.decision is LifecycleDecision.ENTRY_BLOCKED


def test_trigger_and_evidence_are_separate_gates():
    pending = project_trade_lifecycle(plan(), now=NOW, trigger_ready=True)
    eligible = project_trade_lifecycle(
        plan(), now=NOW, trigger_ready=True, execution_evidence_ready=True
    )
    assert pending.stage is LifecycleStage.RISK_GATE
    assert pending.decision is LifecycleDecision.ENTRY_BLOCKED
    assert eligible.stage is LifecycleStage.PAPER_INTENT
    assert eligible.decision is LifecycleDecision.PLAN_PASS
    assert eligible.mutation_allowed is False


def test_position_state_is_projected_after_plan_pass():
    management = PositionManagementResult(
        PositionManagementAction.REVIEW_1R,
        Decimal("1"),
        ("1R_REVIEW_DUE",),
    )
    result = project_trade_lifecycle(
        plan(), now=NOW, position=management, position_id="position-1"
    )
    assert result.stage is LifecycleStage.POSITION_MANAGEMENT
    assert result.decision is LifecycleDecision.POSITION_REVIEW
    assert result.position_id == "position-1"


def test_lifecycle_id_is_versioned_and_time_bound():
    first = project_trade_lifecycle(plan(), now=NOW)
    second = project_trade_lifecycle(plan(), now=NOW + timedelta(seconds=1))
    assert first.lifecycle_id != second.lifecycle_id
    assert first.plan_id == second.plan_id == "plan-1"
