"""Pure Position Management V0.1 classification.

The result is an auditable management decision, not an order.  Stop triggers
are surfaced explicitly, while data/monitoring degradation blocks any claim of
continuous protection.  Execution and broker acknowledgement remain owned by
the existing paper execution path.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from .trade_plan import TradeDirection


class PositionManagementAction(StrEnum):
    HOLD = "HOLD"
    REVIEW_1R = "REVIEW_1R"
    REVIEW_2R = "REVIEW_2R"
    EXIT_HARD_STOP = "EXIT_HARD_STOP"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    PROTECTION_DEGRADED = "PROTECTION_DEGRADED"


@dataclass(frozen=True)
class PositionSnapshot:
    position_id: str
    plan_id: str
    symbol: str
    direction: TradeDirection
    entry_price: Decimal
    initial_stop_price: Decimal
    current_price: Decimal
    quantity: Decimal
    data_quality: str
    monitoring_status: str
    protection_status: str
    timeframe_conflict: bool = False
    disconnected: bool = False

    def __post_init__(self) -> None:
        for field in ("position_id", "plan_id", "symbol"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} is required")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        for field in (
            "entry_price", "initial_stop_price", "current_price", "quantity"
        ):
            try:
                value = Decimal(str(getattr(self, field)))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError(f"{field} must be a finite decimal") from exc
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{field} must be positive and finite")
            object.__setattr__(self, field, value)


@dataclass(frozen=True)
class PositionManagementResult:
    action: PositionManagementAction
    current_r: Decimal | None
    reasons: tuple[str, ...]
    add_allowed: bool = False


def _current_r(position: PositionSnapshot) -> Decimal:
    risk = abs(position.entry_price - position.initial_stop_price)
    if risk <= 0:
        raise ValueError("initial stop must be different from entry")
    move = (
        position.current_price - position.entry_price
        if position.direction is TradeDirection.LONG
        else position.entry_price - position.current_price
    )
    return move / risk


def evaluate_position_management(
    position: PositionSnapshot,
) -> PositionManagementResult:
    """Classify the next review state without mutating a position or order."""

    current_r = _current_r(position)
    reasons: list[str] = []

    if position.disconnected or position.data_quality.upper() != "PASS":
        reasons.append("DATA_OR_CONNECTION_DEGRADED")
    if position.monitoring_status.upper() != "PASS":
        reasons.append("POSITION_MONITORING_NOT_VERIFIED")
    if position.protection_status.upper() != "PASS":
        reasons.append("PROTECTIVE_STOP_NOT_ACKED")

    if position.disconnected or position.data_quality.upper() != "PASS":
        return PositionManagementResult(
            PositionManagementAction.PROTECTION_DEGRADED,
            current_r,
            tuple(reasons),
        )

    stop_hit = (
        position.current_price <= position.initial_stop_price
        if position.direction is TradeDirection.LONG
        else position.current_price >= position.initial_stop_price
    )
    if stop_hit:
        return PositionManagementResult(
            PositionManagementAction.EXIT_HARD_STOP,
            current_r,
            tuple((*reasons, "PROTECTIVE_STOP_TRIGGERED")),
        )

    if position.timeframe_conflict:
        return PositionManagementResult(
            PositionManagementAction.REVIEW_REQUIRED,
            current_r,
            tuple((*reasons, "MULTI_TIMEFRAME_CONFLICT")),
        )

    if current_r >= Decimal("2"):
        return PositionManagementResult(
            PositionManagementAction.REVIEW_2R,
            current_r,
            tuple((*reasons, "1R_AND_2R_REVIEW_DUE")),
        )
    if current_r >= Decimal("1"):
        return PositionManagementResult(
            PositionManagementAction.REVIEW_1R,
            current_r,
            tuple((*reasons, "1R_REVIEW_DUE")),
        )
    return PositionManagementResult(
        PositionManagementAction.HOLD,
        current_r,
        tuple(reasons),
    )
