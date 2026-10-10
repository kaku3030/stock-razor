from decimal import Decimal

from src.services.position_management import (
    PositionManagementAction,
    PositionSnapshot,
    evaluate_position_management,
)
from src.services.trade_plan import TradeDirection


def position(**overrides):
    values = dict(
        position_id="position-1",
        plan_id="plan-1",
        symbol="AAPL",
        direction=TradeDirection.LONG,
        entry_price=Decimal("100"),
        initial_stop_price=Decimal("98"),
        current_price=Decimal("100.50"),
        quantity=Decimal("1"),
        data_quality="PASS",
        monitoring_status="PASS",
        protection_status="PASS",
    )
    values.update(overrides)
    return PositionSnapshot(**values)


def test_hold_and_compute_r_without_mutating_position():
    result = evaluate_position_management(position())
    assert result.action is PositionManagementAction.HOLD
    assert result.current_r == Decimal("0.25")
    assert result.add_allowed is False


def test_one_r_and_two_r_are_review_events_not_automatic_adds():
    one_r = evaluate_position_management(position(current_price=Decimal("102")))
    two_r = evaluate_position_management(position(current_price=Decimal("104")))
    assert one_r.action is PositionManagementAction.REVIEW_1R
    assert two_r.action is PositionManagementAction.REVIEW_2R
    assert one_r.add_allowed is False and two_r.add_allowed is False


def test_hard_stop_is_explicit_exit_candidate():
    result = evaluate_position_management(position(current_price=Decimal("98")))
    assert result.action is PositionManagementAction.EXIT_HARD_STOP
    assert "PROTECTIVE_STOP_TRIGGERED" in result.reasons


def test_disconnect_or_bad_data_blocks_protection_claim():
    result = evaluate_position_management(
        position(current_price=Decimal("110"), disconnected=True)
    )
    assert result.action is PositionManagementAction.PROTECTION_DEGRADED
    assert "DATA_OR_CONNECTION_DEGRADED" in result.reasons


def test_timeframe_conflict_requires_review_before_management_change():
    result = evaluate_position_management(
        position(current_price=Decimal("102"), timeframe_conflict=True)
    )
    assert result.action is PositionManagementAction.REVIEW_REQUIRED
    assert "MULTI_TIMEFRAME_CONFLICT" in result.reasons


def test_short_stop_direction_is_inverted():
    result = evaluate_position_management(
        position(
            direction=TradeDirection.SHORT,
            entry_price=Decimal("100"),
            initial_stop_price=Decimal("102"),
            current_price=Decimal("102"),
        )
    )
    assert result.action is PositionManagementAction.EXIT_HARD_STOP
