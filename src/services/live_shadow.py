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
        _validate_shadow_payload(payload)
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


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionBlocked(f"shadow event field {field} is required")
    return value


def _validate_shadow_payload(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ExecutionBlocked("shadow decision payload must be an object")
    for field in ("decision_id", "intent_id", "decision_at", "risk_result", "gate_result"):
        _required_text(payload.get(field), field)
    try:
        decision_at = datetime.fromisoformat(payload["decision_at"])
    except (TypeError, ValueError) as exc:
        raise ExecutionBlocked("shadow decision timestamp is invalid") from exc
    if decision_at.tzinfo is None:
        raise ExecutionBlocked("shadow decision timestamp must be timezone-aware")
    if payload["risk_result"] not in {"PASS", "BLOCKED"} or payload["gate_result"] not in {"QUALIFIED", "NOT_QUALIFIED"}:
        raise ExecutionBlocked("shadow decision status is invalid")
    if payload["risk_result"] == "PASS" and payload["gate_result"] != "QUALIFIED":
        raise ExecutionBlocked("shadow decision status is inconsistent")
    if payload["risk_result"] == "BLOCKED" and payload["gate_result"] != "NOT_QUALIFIED":
        raise ExecutionBlocked("shadow decision status is inconsistent")
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ExecutionBlocked("shadow decision reason is invalid")
    if payload["risk_result"] == "BLOCKED" and (not isinstance(reason, str) or not reason.strip()):
        raise ExecutionBlocked("blocked shadow decision requires a reason")
    raw = payload.get("preview")
    if raw is None:
        if payload["risk_result"] == "PASS":
            raise ExecutionBlocked("qualified shadow decision requires a preview")
        return
    if payload["risk_result"] != "PASS" or not isinstance(raw, dict):
        raise ExecutionBlocked("shadow preview relationship is invalid")
    for field in ("intent_id", "symbol", "side", "order_type", "session", "account_target", "broker_target", "evidence_snapshot_id", "account_snapshot_generation"):
        _required_text(raw.get(field), f"preview.{field}")
    if raw["intent_id"] != payload["intent_id"] or raw["side"] not in {"BUY", "SELL"} or raw["order_type"] not in {"MARKET", "LIMIT"}:
        raise ExecutionBlocked("shadow preview identity or enum is invalid")
    if raw.get("mutation_allowed") is not False:
        raise ExecutionBlocked("shadow preview cannot allow mutation")
    for field, positive in (("qty", True), ("limit_price", False), ("stop_price", False), ("max_slippage", False)):
        value = raw.get(field)
        if value is None:
            continue
        try:
            number = Decimal(value)
        except Exception as exc:
            raise ExecutionBlocked(f"shadow preview numeric field {field} is invalid") from exc
        if not number.is_finite() or (positive and number <= 0) or (not positive and number < 0):
            raise ExecutionBlocked(f"shadow preview numeric field {field} is invalid")
    for field in ("valid_until",):
        if raw.get(field) is not None:
            try:
                timestamp = datetime.fromisoformat(raw[field])
            except (TypeError, ValueError) as exc:
                raise ExecutionBlocked(f"shadow preview timestamp {field} is invalid") from exc
            if timestamp.tzinfo is None:
                raise ExecutionBlocked(f"shadow preview timestamp {field} must be timezone-aware")
            if timestamp < decision_at:
                raise ExecutionBlocked("shadow preview timestamp is causally invalid")


def _validate_shadow_event(event: JournalEvent, decision: ShadowDecision) -> None:
    if event.kind != "SHADOW_DECISION" or event.intent_id != decision.intent_id or event.state is not None:
        raise ExecutionBlocked("shadow event discriminator or state is invalid")
    if event.at.tzinfo is None or event.at != decision.decision_at or not event.evidence_ids or any(not isinstance(value, str) or not value.strip() for value in event.evidence_ids):
        raise ExecutionBlocked("shadow event metadata is invalid")
    details = dict(event.details)
    if set(details) != {"decision_id", "payload"} or details["decision_id"] != decision.decision_id:
        raise ExecutionBlocked("shadow event details are invalid")
    try:
        payload = json.loads(details["payload"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ExecutionBlocked("shadow event payload is malformed") from exc
    _validate_shadow_payload(payload)
    if payload != decision.to_payload():
        raise ExecutionBlocked("shadow event payload does not match decision")
    expected_evidence = decision.preview.evidence_snapshot_id if decision.preview is not None else event.evidence_ids[0]
    if event.evidence_ids != (expected_evidence,):
        raise ExecutionBlocked("shadow event evidence lineage is invalid")


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

    def _append_shadow_decision(self, intent: OrderIntent, event: JournalEvent, decision: ShadowDecision) -> None:
        _validate_shadow_event(event, decision)
        self._store.save_intent_and_append(intent, event)

    def preview(self, intent: OrderIntent, context: RiskContext, reconciliation: ReconciliationSnapshot,
                account_snapshot_generation: str) -> ShadowDecision:
        if not account_snapshot_generation.strip():
            raise ExecutionBlocked("account snapshot generation is required")
        decision_id = _qualification_identity(intent, context, account_snapshot_generation)
        existing = self._existing(decision_id)
        if existing is not None:
            return existing
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
        self._append_shadow_decision(intent, event, decision)
        return decision
