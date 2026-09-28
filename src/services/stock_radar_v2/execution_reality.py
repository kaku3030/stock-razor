"""Causal, replayable shadow-execution records; no live execution owner."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
from datetime import datetime
from typing import Any, Iterable


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
    OBSERVED = "OBSERVED"
    DIVERGED = "DIVERGED"
    SAME = "OBSERVED"
    MATCH = "OBSERVED"
    DIVERGENT = "DIVERGED"


@dataclass(frozen=True)
class DataSourceObservation:
    source_id: str
    generation: str
    observed_at: datetime
    value: str
    evidence_id: str

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value.strip() for value in (self.source_id, self.generation, self.value, self.evidence_id)):
            raise ValueError("source observation identity, value, and evidence are required")
        if self.observed_at.tzinfo is None:
            raise ValueError("source observation timestamp must be timezone-aware")

    def to_dict(self) -> dict[str, str]:
        return {"source_id": self.source_id, "generation": self.generation, "observed_at": self.observed_at.isoformat(), "value": self.value, "evidence_id": self.evidence_id}

    @classmethod
    def from_dict(cls, value: dict[str, str]) -> "DataSourceObservation":
        return cls(value["source_id"], value["generation"], datetime.fromisoformat(value["observed_at"]), value["value"], value["evidence_id"])


@dataclass(frozen=True)
class ShadowDivergenceRecord:
    preview_identity: str
    observed_outcome: str | None = None
    data_source: DivergenceStatus = DivergenceStatus.UNKNOWN
    account_truth: DivergenceStatus = DivergenceStatus.UNKNOWN
    decision: DivergenceStatus = DivergenceStatus.UNKNOWN
    latency: DivergenceStatus = DivergenceStatus.UNKNOWN
    observations: tuple[DataSourceObservation, ...] = ()

    def compare_observed(self, observed_outcome: str) -> "ShadowDivergenceRecord":
        return ShadowDivergenceRecord(self.preview_identity, observed_outcome, self.data_source,
                                      self.account_truth, self.decision, self.latency, self.observations)

    def compare_sources(self, observations: Iterable[DataSourceObservation]) -> "ShadowDivergenceRecord":
        items = tuple(observations)
        if len(items) < 2 or len({item.source_id for item in items}) != len(items) or len({item.generation for item in items}) != len(items):
            status = DivergenceStatus.UNKNOWN
        else:
            status = DivergenceStatus.OBSERVED if len({item.value for item in items}) == 1 else DivergenceStatus.DIVERGED
        return ShadowDivergenceRecord(self.preview_identity, self.observed_outcome, status,
                                      self.account_truth, self.decision, self.latency, items)

    def to_dict(self) -> dict[str, Any]:
        return {"preview_identity": self.preview_identity, "observed_outcome": self.observed_outcome,
                "data_source": self.data_source.value, "account_truth": self.account_truth.value,
                "decision": self.decision.value, "latency": self.latency.value,
                "observations": [item.to_dict() for item in self.observations]}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ShadowDivergenceRecord":
        observations = tuple(DataSourceObservation.from_dict(item) for item in value.get("observations", ()))
        return cls(value["preview_identity"], value.get("observed_outcome"), DivergenceStatus(value.get("data_source", "UNKNOWN")),
                   DivergenceStatus(value.get("account_truth", "UNKNOWN")), DivergenceStatus(value.get("decision", "UNKNOWN")),
                   DivergenceStatus(value.get("latency", "UNKNOWN")), observations)

    def serialize(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


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
