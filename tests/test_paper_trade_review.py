from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.services.execution_engine import Side
from src.services.paper_trade_review import (
    PaperReplayFill,
    PaperReviewStatus,
    review_completed_paper_trade,
)
from src.services.trade_plan import TradeDirection, TradeHorizon, TradePlan


NOW = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


def plan(**changes):
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
        quantity=Decimal("10"),
        risk_budget_r=Decimal("1"),
        estimated_cost=Decimal("0.1"),
        estimated_slippage=Decimal("0.05"),
        source="offline-replay",
        quote_age_seconds=0,
        monitoring_status="PASS",
        protection_status="SIMULATED",
    )
    values.update(changes)
    return TradePlan(**values)


def fill(side, price, at, quantity=Decimal("10"), fee=Decimal("0")):
    return PaperReplayFill(side, quantity, Decimal(price), at, Decimal(fee))


def test_completed_long_trade_reports_realized_r_and_excursions():
    result = review_completed_paper_trade(
        plan(),
        fill(Side.BUY, "100", NOW),
        fill(Side.SELL, "104", NOW + timedelta(minutes=20), fee="1"),
        observed_prices=(Decimal("99"), Decimal("106")),
    )
    assert result.status is PaperReviewStatus.COMPLETED
    assert result.realized_pnl == Decimal("39")
    assert result.realized_r == Decimal("39") / Decimal("20")
    assert result.mae_r == Decimal("-0.5")
    assert result.mfe_r == Decimal("1.5")


def test_short_trade_uses_inverted_risk_geometry():
    result = review_completed_paper_trade(
        plan(direction=TradeDirection.SHORT, stop_price=Decimal("102")),
        fill(Side.SELL, "100", NOW),
        fill(Side.BUY, "96", NOW + timedelta(minutes=20)),
        observed_prices=(Decimal("103"), Decimal("94")),
    )
    assert result.status is PaperReviewStatus.COMPLETED
    assert result.realized_pnl == Decimal("40")
    assert result.realized_r == Decimal("1")
    assert result.mae_r == Decimal("-1.5")
    assert result.mfe_r == Decimal("3")


def test_review_fails_closed_on_direction_quantity_and_stop_errors():
    assert review_completed_paper_trade(
        plan(), fill(Side.SELL, "100", NOW), fill(Side.BUY, "99", NOW + timedelta(minutes=1))
    ).reasons == ("FILL_DIRECTION_MISMATCH",)
    assert review_completed_paper_trade(
        plan(),
        fill(Side.BUY, "100", NOW),
        fill(
            Side.SELL,
            "99",
            NOW + timedelta(minutes=1),
            quantity=Decimal("9"),
        ),
    ).reasons == ("ENTRY_EXIT_QUANTITY_MISMATCH",)
    assert review_completed_paper_trade(
        plan(stop_price=None),
        fill(Side.BUY, "100", NOW),
        fill(Side.SELL, "99", NOW + timedelta(minutes=1)),
    ).reasons == ("STOP_PRICE_REQUIRED",)
