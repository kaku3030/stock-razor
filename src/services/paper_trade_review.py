"""Pure offline review of one completed paper trade lifecycle.

This module consumes immutable plan/fill evidence only.  It never submits,
cancels, mutates a position, fetches prices, or changes admission gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from .execution_engine import Side
from .trade_plan import TradeDirection, TradePlan


class PaperReviewStatus(StrEnum):
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class PaperReplayFill:
    side: Side
    quantity: Decimal
    price: Decimal
    at: datetime
    fee: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise ValueError("fill timestamp must be timezone-aware")
        object.__setattr__(self, "at", self.at.astimezone(timezone.utc))
        for field in ("quantity", "price", "fee"):
            try:
                value = Decimal(str(getattr(self, field)))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError(f"{field} must be a finite decimal") from exc
            invalid = (
                not value.is_finite()
                or (field != "fee" and value <= 0)
                or (field == "fee" and value < 0)
            )
            if invalid:
                raise ValueError(f"{field} has an invalid value")
            object.__setattr__(self, field, value)


@dataclass(frozen=True)
class PaperTradeReview:
    status: PaperReviewStatus
    plan_id: str
    reasons: tuple[str, ...]
    entry_at: datetime | None = None
    exit_at: datetime | None = None
    quantity: Decimal | None = None
    entry_price: Decimal | None = None
    exit_price: Decimal | None = None
    realized_pnl: Decimal | None = None
    realized_r: Decimal | None = None
    mae_r: Decimal | None = None
    mfe_r: Decimal | None = None


def review_completed_paper_trade(
    plan: TradePlan,
    entry: PaperReplayFill,
    exit: PaperReplayFill,
    *,
    observed_prices: tuple[Decimal, ...] = (),
) -> PaperTradeReview:
    """Review one flat paper lifecycle using deterministic supplied evidence."""

    def blocked(*reasons: str) -> PaperTradeReview:
        return PaperTradeReview(PaperReviewStatus.BLOCKED, plan.plan_id, tuple(reasons))

    if plan.direction is TradeDirection.WAIT:
        return blocked("WAIT_PLAN_NOT_EXECUTABLE")
    expected_entry = Side.BUY if plan.direction is TradeDirection.LONG else Side.SELL
    expected_exit = Side.SELL if expected_entry is Side.BUY else Side.BUY
    if entry.side is not expected_entry or exit.side is not expected_exit:
        return blocked("FILL_DIRECTION_MISMATCH")
    if entry.quantity != exit.quantity:
        return blocked("ENTRY_EXIT_QUANTITY_MISMATCH")
    if exit.at <= entry.at:
        return blocked("EXIT_NOT_AFTER_ENTRY")
    if plan.stop_price is None:
        return blocked("STOP_PRICE_REQUIRED")
    if plan.direction is TradeDirection.LONG:
        risk_per_unit = entry.price - plan.stop_price
        gross = (exit.price - entry.price) * entry.quantity
    else:
        risk_per_unit = plan.stop_price - entry.price
        gross = (entry.price - exit.price) * entry.quantity
    if risk_per_unit <= 0:
        return blocked("NON_POSITIVE_INITIAL_RISK")
    fees = entry.fee + exit.fee
    realized = gross - fees
    initial_risk = risk_per_unit * entry.quantity
    prices = (entry.price, *observed_prices, exit.price)
    if any(Decimal(str(price)) <= 0 for price in prices):
        return blocked("INVALID_OBSERVED_PRICE")
    if plan.direction is TradeDirection.LONG:
        adverse = min(prices) - entry.price
        favorable = max(prices) - entry.price
    else:
        adverse = entry.price - max(prices)
        favorable = entry.price - min(prices)
    return PaperTradeReview(
        status=PaperReviewStatus.COMPLETED,
        plan_id=plan.plan_id,
        reasons=(),
        entry_at=entry.at,
        exit_at=exit.at,
        quantity=entry.quantity,
        entry_price=entry.price,
        exit_price=exit.price,
        realized_pnl=realized,
        realized_r=realized / initial_risk,
        mae_r=adverse * entry.quantity / initial_risk,
        mfe_r=favorable * entry.quantity / initial_risk,
    )
