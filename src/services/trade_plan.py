"""Immutable TradePlan V0.2 contract and entry gate.

This module is deliberately pure: it does not fetch market data, choose a
strategy, create an order, or call a broker.  It only validates that an
upstream decision supplied a complete, time-bounded, risk-bound plan before a
future adapter may translate it into the existing paper admission path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class TradeDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    WAIT = "WAIT"


class TradeHorizon(StrEnum):
    INTRADAY = "INTRADAY"
    SWING = "SWING"
    POSITION = "POSITION"


class TradePlanStatus(StrEnum):
    PLAN_PASS = "PLAN_PASS"
    ENTRY_BLOCKED = "ENTRY_BLOCKED"


def _decimal(value: object | None, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    return result


def _aware(value: datetime | None, field: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TradePlan:
    """One versioned recommendation, independent from execution state."""

    plan_id: str
    version: str
    symbol: str
    direction: TradeDirection
    strategy: str
    horizon: TradeHorizon
    entry_low: Decimal | None
    entry_high: Decimal | None
    entry_ttl: datetime | None
    trigger_frame: str | None
    invalidation: str | None
    stop_price: Decimal | None
    target_price: Decimal | None
    quantity: Decimal | None
    risk_budget_r: Decimal | None
    estimated_cost: Decimal | None
    estimated_slippage: Decimal | None
    source: str | None
    quote_age_seconds: int | None
    monitoring_status: str | None
    protection_status: str | None
    short_permission: bool | None = None
    borrow_available: bool | None = None
    margin_available: bool | None = None
    recall_stress_checked: bool | None = None

    def __post_init__(self) -> None:
        for field in ("plan_id", "version", "symbol", "strategy"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} is required")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "entry_low", _decimal(self.entry_low, "entry_low"))
        object.__setattr__(self, "entry_high", _decimal(self.entry_high, "entry_high"))
        object.__setattr__(self, "stop_price", _decimal(self.stop_price, "stop_price"))
        object.__setattr__(self, "target_price", _decimal(self.target_price, "target_price"))
        object.__setattr__(self, "quantity", _decimal(self.quantity, "quantity"))
        object.__setattr__(self, "risk_budget_r", _decimal(self.risk_budget_r, "risk_budget_r"))
        object.__setattr__(self, "estimated_cost", _decimal(self.estimated_cost, "estimated_cost"))
        object.__setattr__(self, "estimated_slippage", _decimal(self.estimated_slippage, "estimated_slippage"))
        object.__setattr__(self, "entry_ttl", _aware(self.entry_ttl, "entry_ttl"))


@dataclass(frozen=True)
class TradePlanAdmission:
    status: TradePlanStatus
    reasons: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.status is TradePlanStatus.PLAN_PASS


def evaluate_trade_plan(plan: TradePlan, *, now: datetime) -> TradePlanAdmission:
    """Return a fail-closed admission result without producing an order."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now_utc = now.astimezone(timezone.utc)

    if plan.direction is TradeDirection.WAIT:
        return TradePlanAdmission(TradePlanStatus.ENTRY_BLOCKED, ("WAIT_NO_ENTRY",))

    missing = []
    required = {
        "entry_band": plan.entry_low is not None and plan.entry_high is not None,
        "entry_ttl": plan.entry_ttl is not None,
        "trigger_frame": bool(plan.trigger_frame),
        "invalidation": bool(plan.invalidation),
        "stop_price": plan.stop_price is not None,
        "target_price": plan.target_price is not None,
        "quantity": plan.quantity is not None,
        "risk_budget_r": plan.risk_budget_r is not None,
        "estimated_cost": plan.estimated_cost is not None,
        "estimated_slippage": plan.estimated_slippage is not None,
        "source": bool(plan.source),
        "quote_age": plan.quote_age_seconds is not None,
        "monitoring_status": bool(plan.monitoring_status),
        "protection_status": bool(plan.protection_status),
    }
    missing.extend(field for field, present in required.items() if not present)
    if missing:
        return TradePlanAdmission(
            TradePlanStatus.ENTRY_BLOCKED,
            tuple(f"MISSING_{field.upper()}" for field in missing),
        )

    assert plan.entry_low is not None and plan.entry_high is not None
    assert plan.entry_ttl is not None and plan.stop_price is not None
    assert plan.target_price is not None and plan.quantity is not None
    assert plan.risk_budget_r is not None and plan.quote_age_seconds is not None

    reasons: list[str] = []
    if plan.entry_low <= 0 or plan.entry_high < plan.entry_low:
        reasons.append("INVALID_ENTRY_BAND")
    if plan.entry_ttl <= now_utc:
        reasons.append("ENTRY_TTL_EXPIRED")
    if plan.quantity <= 0 or plan.risk_budget_r <= 0:
        reasons.append("INVALID_RISK_SIZE")
    if plan.estimated_cost is None or plan.estimated_cost < 0:
        reasons.append("COST_ESTIMATE_REQUIRED")
    if plan.estimated_slippage is None or plan.estimated_slippage < 0:
        reasons.append("SLIPPAGE_ESTIMATE_REQUIRED")
    if plan.quote_age_seconds < 0:
        reasons.append("INVALID_QUOTE_AGE")

    if plan.direction is TradeDirection.LONG:
        if plan.stop_price >= plan.entry_low:
            reasons.append("LONG_STOP_NOT_PROTECTIVE")
        if plan.target_price <= plan.entry_high:
            reasons.append("LONG_TARGET_NOT_ABOVE_ENTRY")
    else:
        if plan.stop_price <= plan.entry_high:
            reasons.append("SHORT_STOP_NOT_PROTECTIVE")
        if plan.target_price >= plan.entry_low:
            reasons.append("SHORT_TARGET_NOT_BELOW_ENTRY")
        if plan.short_permission is not True:
            reasons.append("SHORT_PERMISSION_UNKNOWN")
        if plan.borrow_available is not True:
            reasons.append("BORROW_UNKNOWN")
        if plan.margin_available is not True:
            reasons.append("MARGIN_UNKNOWN")
        if plan.recall_stress_checked is not True:
            reasons.append("RECALL_STRESS_UNKNOWN")

    if reasons:
        return TradePlanAdmission(TradePlanStatus.ENTRY_BLOCKED, tuple(reasons))
    return TradePlanAdmission(TradePlanStatus.PLAN_PASS, ())
