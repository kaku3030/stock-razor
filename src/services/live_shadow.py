"""Offline live-shadow preview capability with no broker mutation surface."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json

from .execution_engine import (
    ExecutionBlocked,
    ExecutionStore,
    JournalEvent,
    OrderIntent,
    ReconciliationSnapshot,
    RiskContext,
    RiskGuard,
)


@dataclass(frozen=True)
class ShadowPreview:
    intent_id: str
    symbol: str
    side: str
    order_type: str
    qty: Decimal
    limit_price: Decimal | None
    stop_price: Decimal | None
    max_slippage: Decimal | None
    valid_until: datetime | None
    session: str
    account_target: str
    broker_target: str
    evidence_snapshot_id: str
    account_snapshot_generation: str
    mutation_allowed: bool = False


@dataclass(frozen=True)
class ShadowDecision:
    decision_id: str
    intent_id: str
    decision_at: datetime
    risk_result: str
    gate_result: str
    reason: str | None
    preview: ShadowPreview | None

    @property
    def eligible_for_execution(self) -> bool:
        return self.risk_result == "PASS" and self.gate_result == "QUALIFIED" and self.preview is not None

    def to_payload(self) -> dict[str, object]:
        preview = None
        if self.preview is not None:
            preview = {
                "intent_id": self.preview.intent_id, "symbol": self.preview.symbol, "side": self.preview.side,
                "order_type": self.preview.order_type, "qty": str(self.preview.qty),
                "limit_price": str(self.preview.limit_price) if self.preview.limit_price is not None else None,
                "stop_price": str(self.preview.stop_price) if self.preview.stop_price is not None else None,
                "max_slippage": str(self.preview.max_slippage) if self.preview.max_slippage is not None else None,
                "valid_until": self.preview.valid_until.isoformat() if self.preview.valid_until else None,
                "session": self.preview.session, "account_target": self.preview.account_target,
                "broker_target": self.preview.broker_target, "evidence_snapshot_id": self.preview.evidence_snapshot_id,
                "account_snapshot_generation": self.preview.account_snapshot_generation,
                "mutation_allowed": self.preview.mutation_allowed,
            }
        return {"decision_id": self.decision_id, "intent_id": self.intent_id, "decision_at": self.decision_at.isoformat(),
                "risk_result": self.risk_result, "gate_result": self.gate_result, "reason": self.reason, "preview": preview}

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "ShadowDecision":
        raw = payload.get("preview")
        preview = None
        if isinstance(raw, dict):
            preview = ShadowPreview(raw["intent_id"], raw["symbol"], raw["side"], raw["order_type"], Decimal(raw["qty"]),
                                    Decimal(raw["limit_price"]) if raw.get("limit_price") else None,
                                    Decimal(raw["stop_price"]) if raw.get("stop_price") else None,
                                    Decimal(raw["max_slippage"]) if raw.get("max_slippage") else None,
                                    datetime.fromisoformat(raw["valid_until"]) if raw.get("valid_until") else None,
                                    raw["session"], raw["account_target"], raw["broker_target"],
                                    raw["evidence_snapshot_id"], raw["account_snapshot_generation"],
                                    bool(raw["mutation_allowed"]))
        return cls(payload["decision_id"], payload["intent_id"], datetime.fromisoformat(payload["decision_at"]),
                   payload["risk_result"], payload["gate_result"], payload.get("reason"), preview)


def _qualification_identity(intent: OrderIntent, context: RiskContext, account_generation: str) -> str:
    value = {"intent_id": intent.intent_id, "intent": {"symbol": intent.symbol, "side": intent.side.value,
             "order_type": intent.order_type.value, "qty": str(intent.qty), "limit_price": str(intent.limit_price),
             "stop_price": str(intent.stop_price), "max_slippage": str(intent.max_slippage),
             "valid_until": intent.valid_until.isoformat() if intent.valid_until else None},
             "context": {"now": context.now.isoformat(), "data_as_of": context.data_as_of.isoformat() if context.data_as_of else None,
                         "session": context.session, "account_generation": account_generation}}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ShadowExecutionCapability:
    """The only public operation is ``preview``; it has no broker adapter."""
    __slots__ = ("_risk_guard", "_store")

    def __init__(self, risk_guard: RiskGuard, store: ExecutionStore | None = None) -> None:
        self._risk_guard = risk_guard
        self._store = store or ExecutionStore()

    def _existing(self, decision_id: str) -> ShadowDecision | None:
        for event in self._store.events():
            details = dict(event.details)
            if event.kind == "SHADOW_DECISION" and details.get("decision_id") == decision_id:
                return ShadowDecision.from_payload(json.loads(details["payload"]))
        return None

    def preview(self, intent: OrderIntent, context: RiskContext, reconciliation: ReconciliationSnapshot,
                account_snapshot_generation: str) -> ShadowDecision:
        if not account_snapshot_generation.strip():
            raise ExecutionBlocked("account snapshot generation is required")
        decision_id = _qualification_identity(intent, context, account_snapshot_generation)
        existing = self._existing(decision_id)
        if existing is not None:
            return existing
        self._store.save_intent(intent)
        try:
            self._risk_guard.check(intent, reconciliation, context)
        except ExecutionBlocked as exc:
            decision = ShadowDecision(decision_id, intent.intent_id, context.now, "BLOCKED", "NOT_QUALIFIED", str(exc), None)
        else:
            preview = ShadowPreview(intent.intent_id, intent.symbol, intent.side.value, intent.order_type.value, intent.qty,
                                   intent.limit_price, intent.stop_price, intent.max_slippage, intent.valid_until,
                                   intent.allowed_session, intent.account_target, intent.broker_target,
                                   intent.evidence_snapshot_id, account_snapshot_generation)
            decision = ShadowDecision(decision_id, intent.intent_id, context.now, "PASS", "QUALIFIED", None, preview)
        event = JournalEvent(0, "SHADOW_DECISION", intent.intent_id, None, (intent.evidence_snapshot_id,), context.now,
                             (("decision_id", decision_id), ("payload", json.dumps(decision.to_payload(), sort_keys=True))))
        self._store.append(event)
        return decision
