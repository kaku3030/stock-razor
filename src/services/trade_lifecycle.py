"""Read-only Trade Lifecycle V0.3 status projection.

This module joins the pure TradePlan and Position Management classifiers into
one auditable state.  It is a projection only: no order, notification, broker,
market-data, or persistence side effect is allowed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from .position_management import PositionManagementResult, evaluate_position_management
from .trade_plan import TradePlan, TradePlanStatus, evaluate_trade_plan


class LifecycleStage(StrEnum):
    PLAN = "PLAN"
    FAST_TRIGGER = "FAST_TRIGGER"
    RISK_GATE = "RISK_GATE"
    PAPER_INTENT = "PAPER_INTENT"
    POSITION_MANAGEMENT = "POSITION_MANAGEMENT"


class LifecycleDecision(StrEnum):
    WAIT = "WAIT"
    NO_TRADE = "NO_TRADE"
    ENTRY_BLOCKED = "ENTRY_BLOCKED"
    PLAN_PASS = "PLAN_PASS"
    POSITION_REVIEW = "POSITION_REVIEW"


@dataclass(frozen=True)
class TradeLifecycleSnapshot:
    lifecycle_id: str
    as_of: datetime
    stage: LifecycleStage
    decision: LifecycleDecision
    plan_id: str
    position_id: str | None
    reasons: tuple[str, ...]
    mutation_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.lifecycle_id.strip() or not self.plan_id.strip():
            raise ValueError("lifecycle_id and plan_id are required")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        object.__setattr__(self, "as_of", self.as_of.astimezone(timezone.utc))
        if self.mutation_allowed:
            raise ValueError("read-only lifecycle snapshot cannot allow mutation")


def project_trade_lifecycle(
    plan: TradePlan,
    *,
    now: datetime,
    trigger_ready: bool = False,
    execution_evidence_ready: bool = False,
    position: PositionManagementResult | None = None,
    position_id: str | None = None,
) -> TradeLifecycleSnapshot:
    """Project current lifecycle state without creating an execution intent."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    as_of = now.astimezone(timezone.utc)
    lifecycle_id = f"{plan.plan_id}:{plan.version}:{int(as_of.timestamp())}"

    plan_result = evaluate_trade_plan(plan, now=as_of)
    if plan_result.status is TradePlanStatus.ENTRY_BLOCKED:
        decision = LifecycleDecision.WAIT if "WAIT_NO_ENTRY" in plan_result.reasons else LifecycleDecision.ENTRY_BLOCKED
        return TradeLifecycleSnapshot(
            lifecycle_id, as_of, LifecycleStage.PLAN, decision, plan.plan_id,
            position_id, plan_result.reasons,
        )

    if position is not None:
        if position_id is None:
            raise ValueError("position_id is required with position management state")
        return TradeLifecycleSnapshot(
            lifecycle_id,
            as_of,
            LifecycleStage.POSITION_MANAGEMENT,
            LifecycleDecision.POSITION_REVIEW,
            plan.plan_id,
            position_id,
            position.reasons,
        )

    if not trigger_ready:
        return TradeLifecycleSnapshot(
            lifecycle_id, as_of, LifecycleStage.FAST_TRIGGER,
            LifecycleDecision.NO_TRADE, plan.plan_id, position_id,
            ("FAST_TRIGGER_NOT_CONFIRMED",),
        )
    if not execution_evidence_ready:
        return TradeLifecycleSnapshot(
            lifecycle_id, as_of, LifecycleStage.RISK_GATE,
            LifecycleDecision.ENTRY_BLOCKED, plan.plan_id, position_id,
            ("EXECUTION_EVIDENCE_NOT_READY",),
        )
    return TradeLifecycleSnapshot(
        lifecycle_id, as_of, LifecycleStage.PAPER_INTENT,
        LifecycleDecision.PLAN_PASS, plan.plan_id, position_id,
        ("PAPER_INTENT_ELIGIBLE_READ_ONLY",),
    )
