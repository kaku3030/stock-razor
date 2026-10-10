from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.services.execution_engine import ExecutionBlocked, Side
from src.services.paper_execution_admission import (
    build_paper_order_intent_from_trade_plan,
)
from src.services.stock_radar_v2.observation_ledger import Observation
from src.services.trade_plan import TradeDirection, TradeHorizon, TradePlan


NOW = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


def evidence() -> Observation:
    return Observation(
        observation_id="obs-aapl-001",
        detector_status="CONFIRMED",
        evidence_ids=("snapshot-aapl-001",),
        strategy_gate_results={"entry_gate": "PASS"},
        strategy_eligible=True,
        portfolio_admissible=True,
        portfolio_block_reasons=(),
        execution_feasible=True,
        decision_available_at=NOW.timestamp() - 2,
        confirmed_at=NOW.timestamp() - 1,
        earliest_executable_at=NOW.timestamp() - 1,
        canonical_permission="PASS",
    )


def trade_plan(**changes) -> TradePlan:
    values = dict(
        plan_id="plan-aapl-001",
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


def test_passed_plan_maps_to_existing_paper_intent_without_submission():
    intent = build_paper_order_intent_from_trade_plan(
        evidence(),
        trade_plan(),
        entry_price=Decimal("100.50"),
        max_slippage=Decimal("0.01"),
        evidence_snapshot_id="snapshot-aapl-001",
        now=NOW,
    )
    assert intent.symbol == "AAPL"
    assert intent.side is Side.BUY
    assert intent.limit_price == Decimal("100.50")
    assert intent.stop_price == Decimal("98")
    assert intent.account_target == "paper"


def test_trigger_price_must_be_inside_precomputed_entry_band():
    with pytest.raises(ExecutionBlocked, match="outside"):
        build_paper_order_intent_from_trade_plan(
            evidence(),
            trade_plan(),
            entry_price=Decimal("102"),
            max_slippage=Decimal("0.01"),
            evidence_snapshot_id="snapshot-aapl-001",
            now=NOW,
        )


def test_blocked_plan_never_reaches_paper_admission():
    with pytest.raises(ExecutionBlocked, match="trade plan is not executable"):
        build_paper_order_intent_from_trade_plan(
            evidence(),
            trade_plan(stop_price=None),
            entry_price=Decimal("100.50"),
            max_slippage=Decimal("0.01"),
            evidence_snapshot_id="snapshot-aapl-001",
            now=NOW,
        )
