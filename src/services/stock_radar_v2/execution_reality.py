"""Causal, replayable shadow-execution records; no live execution owner."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
from typing import Any


class InterruptedReason(StrEnum):
    DATA_QUALITY_LOSS = "DATA_QUALITY_LOSS"
    PROVIDER_OR_RUNTIME_FAILURE = "PROVIDER_OR_RUNTIME_FAILURE"
    EXECUTION_PATH_UNAVAILABLE = "EXECUTION_PATH_UNAVAILABLE"
    SESSION_OR_MARKET_CONSTRAINT = "SESSION_OR_MARKET_CONSTRAINT"
    USER_OR_SYSTEM_CANCEL = "USER_OR_SYSTEM_CANCEL"


class MarketExecutionConstraint(StrEnum):
    T_PLUS_ONE = "T_PLUS_ONE"
    PRICE_LIMIT = "PRICE_LIMIT"
    SUSPENDED = "SUSPENDED"
    QUEUE_OR_LIQUIDITY = "QUEUE_OR_LIQUIDITY"
    SESSION = "SESSION"
    PRE_POST_MARKET = "PRE_POST_MARKET"
    BORROW = "BORROW"


class DivergenceStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    MATCH = "MATCH"
    DIVERGENT = "DIVERGENT"


@dataclass(frozen=True)
class ShadowDivergenceRecord:
    preview_identity: str
    observed_outcome: str | None = None
    data_source: DivergenceStatus = DivergenceStatus.UNKNOWN
    account_truth: DivergenceStatus = DivergenceStatus.UNKNOWN
    decision: DivergenceStatus = DivergenceStatus.UNKNOWN
    latency: DivergenceStatus = DivergenceStatus.UNKNOWN

    def compare_observed(self, observed_outcome: str) -> "ShadowDivergenceRecord":
        return ShadowDivergenceRecord(self.preview_identity, observed_outcome, self.data_source,
                                      self.account_truth, self.decision, self.latency)


@dataclass(frozen=True)
class ShadowExecutionRecord:
    execution_id: str
    order_intent_at: float
    simulated_fill_at: float | None
    fill_price: float | None
    fill_qty: float
    requested_qty: float
    partial_fill: bool
    fill_model_version: str
    slippage_model_version: str
    execution_latency_ms: int | None
    decision_available_at: float | None = None
    confirmed_at: float | None = None
    bar_end_at: float | None = None
    constraints: tuple[MarketExecutionConstraint, ...] = ()
    interrupted_reason: InterruptedReason | None = None

    def __post_init__(self) -> None:
        if self.requested_qty <= 0 or self.fill_qty < 0 or self.fill_qty > self.requested_qty:
            raise ValueError("shadow quantities must satisfy 0 <= fill_qty <= requested_qty")
        if self.partial_fill != (0 < self.fill_qty < self.requested_qty):
            raise ValueError("partial_fill must describe requested_qty versus fill_qty")
        if self.simulated_fill_at is None and any(value is not None for value in (self.fill_price,)):
            raise ValueError("a missing simulated fill cannot have a fill price")
        available = [v for v in (self.decision_available_at, self.confirmed_at) if v is not None]
        if available and self.order_intent_at < max(available):
            raise ValueError("order intent cannot precede decision availability")
        if self.simulated_fill_at is not None and self.simulated_fill_at < self.order_intent_at:
            raise ValueError("simulated fill cannot precede order intent")
        if self.bar_end_at is not None and self.simulated_fill_at is not None and self.confirmed_at is not None:
            if self.confirmed_at <= self.bar_end_at and self.simulated_fill_at <= self.bar_end_at:
                raise ValueError("same-bar hindsight fill is not executable")
        if self.interrupted_reason is not None and self.simulated_fill_at is not None:
            raise ValueError("interrupted shadow execution cannot also claim a fill")

    @property
    def remainder_qty(self) -> float:
        return self.requested_qty - self.fill_qty

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["constraints"] = [item.value for item in self.constraints]
        value["interrupted_reason"] = self.interrupted_reason.value if self.interrupted_reason else None
        return value

    def serialize(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def interrupted(reason: InterruptedReason) -> dict[str, str]:
    """Stable audit payload; does not mutate thesis or market-risk state."""
    return {"status": "INTERRUPTED", "reason": reason.value}
