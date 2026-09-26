"""Deterministic, paper-only admission from explicit upstream permission to OrderIntent.

This module does not own strategy decisions, account truth, market-data collection,
or broker mutation.  It only validates an explicit permission envelope and turns
an explicit paper order specification into the existing Execution Engine intent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from typing import Protocol

from .execution_engine import ExecutionBlocked, OrderIntent, OrderType, Side


class ExecutionAdmissionEvidence(Protocol):
    observation_id: str
    evidence_ids: tuple[str, ...]
    strategy_eligible: bool | None
    portfolio_admissible: bool | None
    portfolio_block_reasons: tuple[str, ...]
    execution_feasible: bool | None
    decision_available_at: float | None
    confirmed_at: float | None
    earliest_executable_at: float | None
    canonical_permission: str


@dataclass(frozen=True)
class PaperOrderSpec:
    """Explicit sizing/price inputs supplied by Main Control; never inferred here."""

    action_id: str
    symbol: str
    side: Side
    qty: Decimal
    limit_price: Decimal
    max_slippage: Decimal
    strategy_id: str
    evidence_snapshot_id: str
    valid_until: datetime
    stop_price: Decimal | None = None
    invalidation: Decimal | None = None
    risk_budget_r: Decimal | None = None
    allowed_session: str = "RTH"


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionBlocked(f"{field} is required")
    return value.strip()


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ExecutionBlocked(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _intent_id(evidence: ExecutionAdmissionEvidence, spec: PaperOrderSpec) -> str:
    """One upstream action maps to one durable paper intent identity.

    Deliberately excludes mutable order fields.  Reusing the same action_id for
    altered payloads therefore collides at the Execution Engine instead of
    silently creating a second order after a retry or operator correction.
    """

    observation_id = _required_text(evidence.observation_id, "observation_id")
    action_id = _required_text(spec.action_id, "action_id")
    strategy_id = _required_text(spec.strategy_id, "strategy_id")
    material = f"paper|{strategy_id}|{observation_id}|{action_id}".encode("utf-8")
    return f"paper-{hashlib.sha256(material).hexdigest()[:24]}"


def _validate_permission(
    evidence: ExecutionAdmissionEvidence,
    spec: PaperOrderSpec,
    *,
    now: datetime,
) -> None:
    permission = _required_text(evidence.canonical_permission, "canonical_permission").upper()
    if permission != "PASS":
        raise ExecutionBlocked("canonical execution permission is not PASS")
    if evidence.strategy_eligible is not True:
        raise ExecutionBlocked("strategy eligibility is not explicitly true")
    if evidence.portfolio_admissible is not True:
        raise ExecutionBlocked("portfolio admission is not explicitly true")
    if evidence.execution_feasible is not True:
        raise ExecutionBlocked("execution feasibility is not explicitly true")
    if tuple(evidence.portfolio_block_reasons):
        raise ExecutionBlocked("portfolio admission contains block reasons")

    evidence_snapshot_id = _required_text(spec.evidence_snapshot_id, "evidence_snapshot_id")
    if evidence_snapshot_id not in tuple(evidence.evidence_ids):
        raise ExecutionBlocked("order evidence is not bound to the permission evidence")

    times = (
        evidence.decision_available_at,
        evidence.confirmed_at,
        evidence.earliest_executable_at,
    )
    if any(value is None for value in times):
        raise ExecutionBlocked("decision, confirmation, and executable timestamps are required")
    decision_at, confirmed_at, earliest_at = (float(value) for value in times)
    if earliest_at < max(decision_at, confirmed_at):
        raise ExecutionBlocked("execution cannot precede decision or confirmation")
    if now.timestamp() < earliest_at:
        raise ExecutionBlocked("execution is not yet causally available")

    valid_until = _utc(spec.valid_until, "valid_until")
    if valid_until <= now:
        raise ExecutionBlocked("paper order specification is expired")
    if spec.allowed_session != "RTH":
        raise ExecutionBlocked("paper admission V0.1 is restricted to RTH")


def build_paper_order_intent(
    evidence: ExecutionAdmissionEvidence,
    spec: PaperOrderSpec,
    *,
    now: datetime,
) -> OrderIntent:
    """Validate an explicit permission and produce a paper-only OrderIntent.

    Risk limits, market-data TTL, account freshness and broker state remain the
    Execution Engine / RiskGuard's responsibility.  This function never calls an
    adapter and cannot select or unlock a live broker.
    """

    now_utc = _utc(now, "now")
    _validate_permission(evidence, spec, now=now_utc)
    return OrderIntent(
        intent_id=_intent_id(evidence, spec),
        symbol=_required_text(spec.symbol, "symbol"),
        side=spec.side,
        order_type=OrderType.LIMIT,
        qty=spec.qty,
        limit_price=spec.limit_price,
        stop_price=spec.stop_price,
        max_slippage=spec.max_slippage,
        invalidation=spec.invalidation,
        risk_budget_r=spec.risk_budget_r,
        valid_until=_utc(spec.valid_until, "valid_until"),
        strategy_id=_required_text(spec.strategy_id, "strategy_id"),
        evidence_snapshot_id=_required_text(spec.evidence_snapshot_id, "evidence_snapshot_id"),
        account_target="paper",
        broker_target="paper",
        allowed_session="RTH",
    )
