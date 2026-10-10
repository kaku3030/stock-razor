from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.services.trade_plan import (
    TradeDecision,
    TradeDirection,
    TradeHorizon,
    TradePlan,
    TradePlanStatus,
    evaluate_trade_plan,
)


NOW = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


def plan(**overrides):
    values = dict(
        plan_id="plan-1",
        version="trade-plan-v0.2",
        symbol="AAPL",
        direction=TradeDirection.LONG,
        strategy="breakout-retest",
        horizon=TradeHorizon.INTRADAY,
        entry_low=Decimal("100"),
        entry_high=Decimal("101"),
        entry_ttl=NOW + timedelta(minutes=15),
        trigger_frame="5m",
        invalidation="close below failed-retest low",
        stop_price=Decimal("98"),
        target_price=Decimal("106"),
        quantity=Decimal("1"),
        risk_budget_r=Decimal("1"),
        estimated_cost=Decimal("0.10"),
        estimated_slippage=Decimal("0.05"),
        source="opend-readonly",
        quote_age_seconds=2,
        monitoring_status="READY",
        protection_status="PLANNED_NOT_ACKED",
    )
    values.update(overrides)
    return TradePlan(**values)


def test_complete_long_plan_passes_without_creating_order():
    result = evaluate_trade_plan(plan(), now=NOW)
    assert result.status is TradePlanStatus.PLAN_PASS
    assert result.passed is True
    assert result.reasons == ()


def test_wait_is_a_valid_no_trade_decision_but_not_an_entry_pass():
    result = evaluate_trade_plan(plan(direction=TradeDirection.WAIT), now=NOW)
    assert result.status is TradePlanStatus.WAIT
    assert result.reasons == ("WAIT_NO_ENTRY",)


def test_explicit_no_trade_is_distinct_and_does_not_require_entry_fields():
    result = evaluate_trade_plan(
        plan(
            decision=TradeDecision.NO_TRADE,
            entry_low=None,
            entry_high=None,
            entry_ttl=None,
            trigger_frame=None,
            invalidation=None,
            stop_price=None,
            target_price=None,
            quantity=None,
            risk_budget_r=None,
            estimated_cost=None,
            estimated_slippage=None,
            source=None,
            quote_age_seconds=None,
            monitoring_status=None,
            protection_status=None,
        ),
        now=NOW,
    )
    assert result.status is TradePlanStatus.NO_TRADE
    assert result.passed is False
    assert result.reasons == ("NO_TRADE_DECLARED",)


def test_missing_protection_and_costs_fail_closed():
    result = evaluate_trade_plan(
        plan(stop_price=None, estimated_cost=None, protection_status=None), now=NOW
    )
    assert result.status is TradePlanStatus.ENTRY_BLOCKED
    assert "MISSING_STOP_PRICE" in result.reasons
    assert "MISSING_ESTIMATED_COST" in result.reasons
    assert "MISSING_PROTECTION_STATUS" in result.reasons


def test_short_requires_real_permission_and_borrow_evidence():
    result = evaluate_trade_plan(
        plan(
            direction=TradeDirection.SHORT,
            entry_low=Decimal("100"),
            entry_high=Decimal("101"),
            stop_price=Decimal("103"),
            target_price=Decimal("95"),
        ),
        now=NOW,
    )
    assert result.status is TradePlanStatus.ENTRY_BLOCKED
    assert "SHORT_PERMISSION_UNKNOWN" in result.reasons
    assert "BORROW_UNKNOWN" in result.reasons
    assert "MARGIN_UNKNOWN" in result.reasons
    assert "RECALL_STRESS_UNKNOWN" in result.reasons


def test_expired_entry_and_bad_long_geometry_fail_closed():
    result = evaluate_trade_plan(
        plan(
            entry_ttl=NOW - timedelta(seconds=1),
            stop_price=Decimal("101"),
            target_price=Decimal("100"),
        ),
        now=NOW,
    )
    assert result.status is TradePlanStatus.ENTRY_BLOCKED
    assert "ENTRY_TTL_EXPIRED" in result.reasons
    assert "LONG_STOP_NOT_PROTECTIVE" in result.reasons
    assert "LONG_TARGET_NOT_ABOVE_ENTRY" in result.reasons
