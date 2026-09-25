"""Offline, recoverable, paper-only execution engine.

The SQLite store is idempotent/recoverable; an ambiguous crash is blocked,
never silently treated as exactly-once or automatically resubmitted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import json
import sqlite3
from pathlib import Path
from typing import Iterable


class ExecutionBlocked(RuntimeError): pass
class PaperOrderRejected(RuntimeError): pass

class Side(StrEnum): BUY = "BUY"; SELL = "SELL"
class OrderType(StrEnum): MARKET = "MARKET"; LIMIT = "LIMIT"
class OrderState(StrEnum):
    INTENT = "INTENT"; VALIDATED = "VALIDATED"; SUBMITTING = "SUBMITTING"; ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"; FILLED = "FILLED"; CANCELLED = "CANCELLED"; REJECTED = "REJECTED"; SUPERSEDED = "SUPERSEDED"
class AdapterMode(StrEnum): PAPER = "PAPER"

TERMINAL_STATES = frozenset({OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.SUPERSEDED})
ALLOWED_TRANSITIONS = {
    OrderState.INTENT: {OrderState.VALIDATED}, OrderState.VALIDATED: {OrderState.SUBMITTING},
    OrderState.SUBMITTING: {OrderState.ACCEPTED, OrderState.REJECTED},
    OrderState.ACCEPTED: {OrderState.PARTIAL, OrderState.FILLED, OrderState.CANCELLED, OrderState.SUPERSEDED},
    OrderState.PARTIAL: {OrderState.PARTIAL, OrderState.FILLED, OrderState.CANCELLED, OrderState.SUPERSEDED},
    OrderState.FILLED: set(), OrderState.CANCELLED: set(), OrderState.REJECTED: set(), OrderState.SUPERSEDED: set(),
}

def _utc(value: datetime) -> datetime:
    if value.tzinfo is None: raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)

def _decimal(value: object, name: str) -> Decimal:
    try: result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc: raise ValueError(f"{name} must be a finite decimal") from exc
    if not result.is_finite(): raise ValueError(f"{name} must be a finite decimal")
    return result

@dataclass(frozen=True)
class OrderIntent:
    intent_id: str; symbol: str; side: Side; order_type: OrderType; qty: Decimal
    limit_price: Decimal | None = None; stop_price: Decimal | None = None; max_slippage: Decimal | None = None
    invalidation: Decimal | None = None; risk_budget_r: Decimal | None = None; valid_until: datetime | None = None
    strategy_id: str = ""; evidence_snapshot_id: str = ""; account_target: str = ""; broker_target: str = ""; allowed_session: str = "RTH"
    def __post_init__(self) -> None:
        if not self.intent_id.strip() or not self.symbol.strip(): raise ValueError("intent_id and symbol are required")
        object.__setattr__(self, "symbol", self.symbol.strip().upper()); qty = _decimal(self.qty, "qty")
        if qty <= 0: raise ValueError("qty must be positive")
        object.__setattr__(self, "qty", qty)
        for name in ("limit_price", "stop_price", "max_slippage", "invalidation", "risk_budget_r"):
            value = getattr(self, name)
            if value is not None: object.__setattr__(self, name, _decimal(value, name))
        if self.order_type is OrderType.LIMIT and (self.limit_price is None or self.limit_price <= 0): raise ValueError("LIMIT intent requires a positive limit_price")
        if self.valid_until is not None: object.__setattr__(self, "valid_until", _utc(self.valid_until))
        if not self.strategy_id or not self.evidence_snapshot_id or not self.account_target or not self.broker_target: raise ValueError("strategy, evidence, account, and broker lineage are required")

@dataclass(frozen=True)
class ResourceSnapshot:
    identity: str; source: str; as_of: datetime; fresh: bool = True; complete: bool = True
    def __post_init__(self) -> None: object.__setattr__(self, "as_of", _utc(self.as_of))

@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str; buying_power: Decimal; equity: Decimal; as_of: datetime; source: str; fresh: bool = True
    def __post_init__(self) -> None:
        object.__setattr__(self, "buying_power", _decimal(self.buying_power, "buying_power")); object.__setattr__(self, "equity", _decimal(self.equity, "equity")); object.__setattr__(self, "as_of", _utc(self.as_of))

@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str; qty: Decimal; market_value: Decimal
    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper()); object.__setattr__(self, "qty", _decimal(self.qty, "position qty")); object.__setattr__(self, "market_value", _decimal(self.market_value, "market_value"))

@dataclass(frozen=True)
class ReconciliationSnapshot:
    account: AccountSnapshot; positions: tuple[PositionSnapshot, ...] = (); open_order_ids: tuple[str, ...] = (); fill_ids: tuple[str, ...] = (); as_of: datetime | None = None; complete: bool = True
    funds: ResourceSnapshot | None = None; positions_resource: ResourceSnapshot | None = None; open_orders_resource: ResourceSnapshot | None = None; fills_resource: ResourceSnapshot | None = None
    def __post_init__(self) -> None:
        if self.as_of is not None: object.__setattr__(self, "as_of", _utc(self.as_of))
    def resources(self) -> tuple[ResourceSnapshot, ...]:
        default = lambda: ResourceSnapshot(self.account.account_id, self.account.source, self.account.as_of, self.account.fresh, self.complete)
        return (ResourceSnapshot(self.account.account_id, self.account.source, self.account.as_of, self.account.fresh, self.complete), self.funds or default(), self.positions_resource or default(), self.open_orders_resource or default(), self.fills_resource or default())

@dataclass(frozen=True)
class RiskLimits:
    allowed_symbols: frozenset[str]; max_order_notional: Decimal; max_order_qty: Decimal; max_symbol_exposure: Decimal; max_portfolio_exposure: Decimal; max_slippage: Decimal; max_open_orders: int; data_ttl_seconds: int; account_ttl_seconds: int; allowed_sessions: frozenset[str] = frozenset({"RTH"}); daily_max_loss: Decimal = Decimal("0")
@dataclass(frozen=True)
class RiskContext:
    now: datetime; data_as_of: datetime | None; session: str; kill_switch: bool = False; daily_loss: Decimal = Decimal("0")
@dataclass(frozen=True)
class JournalEvent:
    sequence: int; kind: str; intent_id: str; state: OrderState | None; evidence_ids: tuple[str, ...]; at: datetime; details: tuple[tuple[str, str], ...] = ()
@dataclass
class OrderRecord:
    intent: OrderIntent; state: OrderState = OrderState.INTENT; broker_order_id: str | None = None; fill_ids: list[str] = field(default_factory=list); filled_qty: Decimal = Decimal("0")

class ExecutionStore:
    """Transactional event store with unique intent/order/fill identities."""
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(str(path)); self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS intents(intent_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, intent_id TEXT NOT NULL, state TEXT, evidence_ids TEXT NOT NULL, at TEXT NOT NULL, details TEXT NOT NULL, UNIQUE(intent_id,kind,details));
        CREATE UNIQUE INDEX IF NOT EXISTS event_broker_order ON events(json_extract(details,'$.broker_order_id')) WHERE kind='ACCEPTED' AND json_extract(details,'$.broker_order_id') IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS event_fill ON events(json_extract(details,'$.fill_id')) WHERE kind IN ('PARTIAL','FILLED') AND json_extract(details,'$.fill_id') IS NOT NULL;
        CREATE TRIGGER IF NOT EXISTS events_immutable_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS events_immutable_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS intents_immutable_update BEFORE UPDATE ON intents BEGIN SELECT RAISE(ABORT, 'intents are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS intents_immutable_delete BEFORE DELETE ON intents BEGIN SELECT RAISE(ABORT, 'intents are immutable'); END;
        """); self.connection.commit()
    def save_intent(self, intent: OrderIntent) -> None:
        payload = {"intent_id": intent.intent_id, "symbol": intent.symbol, "side": intent.side.value, "order_type": intent.order_type.value, "qty": str(intent.qty), "limit_price": str(intent.limit_price) if intent.limit_price is not None else None, "max_slippage": str(intent.max_slippage) if intent.max_slippage is not None else None, "strategy_id": intent.strategy_id, "evidence_snapshot_id": intent.evidence_snapshot_id, "account_target": intent.account_target, "broker_target": intent.broker_target, "allowed_session": intent.allowed_session}
        with self.connection: self.connection.execute("INSERT OR IGNORE INTO intents(intent_id,payload) VALUES(?,?)", (intent.intent_id, json.dumps(payload, sort_keys=True)))
    def intents(self) -> list[OrderIntent]:
        result = []
        for (raw,) in self.connection.execute("SELECT payload FROM intents ORDER BY intent_id"):
            item = json.loads(raw); result.append(OrderIntent(item["intent_id"], item["symbol"], Side(item["side"]), OrderType(item["order_type"]), Decimal(item["qty"]), Decimal(item["limit_price"]) if item["limit_price"] else None, max_slippage=Decimal(item["max_slippage"]) if item["max_slippage"] else None, strategy_id=item["strategy_id"], evidence_snapshot_id=item["evidence_snapshot_id"], account_target=item["account_target"], broker_target=item["broker_target"], allowed_session=item["allowed_session"]))
        return result
    def append(self, event: JournalEvent) -> None:
        try:
            with self.connection: self.connection.execute("INSERT INTO events(kind,intent_id,state,evidence_ids,at,details) VALUES(?,?,?,?,?,?)", (event.kind,event.intent_id,event.state.value if event.state else None,json.dumps(event.evidence_ids),event.at.isoformat(),json.dumps(dict(event.details),sort_keys=True)))
        except sqlite3.IntegrityError as exc: raise ExecutionBlocked("duplicate broker or fill identity") from exc
    def events(self) -> list[JournalEvent]:
        rows = self.connection.execute("SELECT sequence,kind,intent_id,state,evidence_ids,at,details FROM events ORDER BY sequence").fetchall()
        return [JournalEvent(r[0],r[1],r[2],OrderState(r[3]) if r[3] else None,tuple(json.loads(r[4])),datetime.fromisoformat(r[5]),tuple(sorted(json.loads(r[6]).items()))) for r in rows]
    def has_ambiguous_submission(self) -> bool:
        return bool(self.connection.execute("SELECT 1 FROM events WHERE state='SUBMITTING' AND intent_id NOT IN (SELECT intent_id FROM events WHERE state IN ('ACCEPTED','REJECTED')) LIMIT 1").fetchone()) or self.has_pending_mutation()
    def has_pending_mutation(self) -> bool:
        return bool(self.connection.execute("""SELECT 1 FROM events requested
            WHERE requested.kind IN ('CANCEL_REQUESTED','REPLACE_REQUESTED')
            AND NOT EXISTS (SELECT 1 FROM events completed
                WHERE completed.intent_id=requested.intent_id
                AND completed.kind IN ('CANCELLED','SUPERSEDED')
                AND completed.sequence > requested.sequence) LIMIT 1""").fetchone())
    def fill_exists(self, fill_id: str) -> bool:
        return bool(self.connection.execute("SELECT 1 FROM events WHERE json_extract(details,'$.fill_id')=?", (fill_id,)).fetchone())

_PAPER_CAPABILITY_TOKEN = object()
class _PaperCapability:
    def __init__(self, adapter: "PaperBrokerAdapter", token: object) -> None:
        if token is not _PAPER_CAPABILITY_TOKEN: raise ExecutionBlocked("paper capability must come from factory")
        self.adapter = adapter
def create_paper_adapter(*, fills: dict[str, tuple[tuple[str, Decimal, Decimal], ...]] | None = None, rejects: frozenset[str] = frozenset()) -> _PaperCapability:
    return _PaperCapability(PaperBrokerAdapter(fills, rejects), _PAPER_CAPABILITY_TOKEN)

class PaperBrokerAdapter:
    def __init__(self, fills: dict[str, tuple[tuple[str, Decimal, Decimal], ...]] | None = None, rejects: frozenset[str] = frozenset()) -> None: self._fills=fills or {}; self._rejects=rejects; self.calls=[]; self._next=0
    def place(self, intent: OrderIntent) -> tuple[str, Iterable[tuple[str, Decimal, Decimal]]]:
        self.calls.append(("place",intent.intent_id))
        if intent.intent_id in self._rejects: raise PaperOrderRejected("paper rejection")
        self._next += 1; return f"paper-order-{self._next}", self._fills.get(intent.intent_id, ())
    def cancel(self, broker_order_id: str) -> None: self.calls.append(("cancel",broker_order_id))
    def replace(self, broker_order_id: str, intent: OrderIntent) -> str:
        self.calls.append(("replace",broker_order_id)); self._next += 1; return f"paper-order-{self._next}"
    def reconcile(self) -> ReconciliationSnapshot:
        now=datetime.now(timezone.utc); return ReconciliationSnapshot(AccountSnapshot("paper",Decimal("100000"),Decimal("100000"),now,"paper"),as_of=now)

def _age_seconds(now: datetime, as_of: datetime | None) -> int | None: return None if as_of is None else int((now-_utc(as_of)).total_seconds())

class RiskGuard:
    def __init__(self, limits: RiskLimits) -> None: self.limits=limits
    def check(self, intent: OrderIntent, recon: ReconciliationSnapshot, context: RiskContext) -> None:
        now=_utc(context.now)
        if context.kill_switch: raise ExecutionBlocked("kill switch is active")
        if context.session not in self.limits.allowed_sessions or intent.allowed_session not in self.limits.allowed_sessions: raise ExecutionBlocked("session is not allowed")
        if intent.symbol not in {s.upper() for s in self.limits.allowed_symbols}: raise ExecutionBlocked("symbol is not whitelisted")
        if intent.account_target != recon.account.account_id or intent.broker_target != recon.account.source: raise ExecutionBlocked("account or broker identity mismatch")
        if intent.valid_until is not None and now > intent.valid_until: raise ExecutionBlocked("intent is expired")
        if recon.as_of is None or _age_seconds(now,recon.as_of) is None or _age_seconds(now,recon.as_of)<0 or _age_seconds(now,recon.as_of)>self.limits.account_ttl_seconds: raise ExecutionBlocked("reconciliation is incomplete or stale")
        for resource in recon.resources():
            if (resource.identity != recon.account.account_id or resource.source != recon.account.source or not recon.complete or not resource.complete or not resource.fresh or _age_seconds(now,resource.as_of) is None or _age_seconds(now,resource.as_of)<0 or _age_seconds(now,resource.as_of)>self.limits.account_ttl_seconds): raise ExecutionBlocked("reconciliation is incomplete or stale")
        if _age_seconds(now,context.data_as_of) is None or _age_seconds(now,context.data_as_of)<0 or _age_seconds(now,context.data_as_of)>self.limits.data_ttl_seconds: raise ExecutionBlocked("market data is stale or unknown")
        if len(recon.open_order_ids)>=self.limits.max_open_orders: raise ExecutionBlocked("outstanding-order cap reached")
        if intent.qty>self.limits.max_order_qty: raise ExecutionBlocked("order quantity exceeds limit")
        if intent.limit_price is None: raise ExecutionBlocked("paper V0.1 requires a limit reference price")
        notional=intent.qty*intent.limit_price
        if notional>self.limits.max_order_notional: raise ExecutionBlocked("order notional exceeds limit")
        if intent.side is Side.BUY and notional>recon.account.buying_power: raise ExecutionBlocked("insufficient buying power")
        if intent.max_slippage is None or intent.max_slippage>self.limits.max_slippage: raise ExecutionBlocked("slippage budget is missing or exceeds limit")
        if self.limits.daily_max_loss>0 and _decimal(context.daily_loss,"daily_loss")>=self.limits.daily_max_loss: raise ExecutionBlocked("daily loss limit reached")
        symbol=sum((p.market_value for p in recon.positions if p.symbol==intent.symbol),Decimal("0")); portfolio=sum((p.market_value for p in recon.positions),Decimal("0"))
        if symbol+notional>self.limits.max_symbol_exposure: raise ExecutionBlocked("symbol exposure exceeds limit")
        if portfolio+notional>self.limits.max_portfolio_exposure: raise ExecutionBlocked("portfolio exposure exceeds limit")

class ExecutionEngine:
    def __init__(self, capability: _PaperCapability, risk_guard: RiskGuard, store: ExecutionStore | None = None) -> None:
        if not isinstance(capability,_PaperCapability): raise ExecutionBlocked("only factory-issued paper capability is enabled")
        self.adapter=capability.adapter; self.risk_guard=risk_guard; self.store=store or ExecutionStore(); self.journal=tuple(self.store.events()); self.records={intent.intent_id: OrderRecord(intent) for intent in self.store.intents()}
        for event in self.journal:
            record = self.records.get(event.intent_id)
            if record is not None and event.state is not None: record.state = event.state
            if record is not None:
                details = dict(event.details)
                if details.get("broker_order_id"): record.broker_order_id = details["broker_order_id"]
                if details.get("fill_id") and details["fill_id"] not in record.fill_ids:
                    record.fill_ids.append(details["fill_id"]); record.filled_qty += Decimal(details.get("quantity", "0"))
        if self.store.has_ambiguous_submission(): raise ExecutionBlocked("ambiguous submission requires resync; automatic resubmit is blocked")
        self.reconciliation=None
    def _append(self, kind: str, record: OrderRecord, at: datetime, **details: object) -> None:
        event=JournalEvent(len(self.journal)+1,kind,record.intent.intent_id,details.pop("_state",record.state),(record.intent.evidence_snapshot_id,*record.fill_ids),_utc(at),tuple(sorted((str(k),str(v)) for k,v in details.items())))
        self.store.append(event); self.journal+=(event,)
    def _transition(self, record: OrderRecord, state: OrderState, at: datetime, **details: object) -> None:
        if state not in ALLOWED_TRANSITIONS[record.state]: raise ExecutionBlocked(f"invalid transition {record.state}->{state}")
        self._append(state.value,record,at,_state=state,**details); record.state=state
    def _mutation_gate(self, intent: OrderIntent, context: RiskContext) -> None:
        if self.reconciliation is None: raise ExecutionBlocked("reconciliation is required")
        self.risk_guard.check(intent,self.reconciliation,context)
        if self.store.has_ambiguous_submission(): raise ExecutionBlocked("pending mutation requires resync")
    def reconcile(self) -> ReconciliationSnapshot:
        snapshot=self.adapter.reconcile(); self.reconciliation=snapshot
        if snapshot.as_of is None or not snapshot.complete or any(r.identity != snapshot.account.account_id or r.source != snapshot.account.source or not r.complete or not r.fresh for r in snapshot.resources()): raise ExecutionBlocked("reconciliation is incomplete or stale")
        return snapshot
    def submit(self, intent: OrderIntent, context: RiskContext) -> OrderRecord:
        if intent.intent_id in self.records or any(e.intent_id==intent.intent_id for e in self.journal): raise ExecutionBlocked("duplicate intent_id")
        if self.reconciliation is None: raise ExecutionBlocked("startup reconciliation is required")
        self.risk_guard.check(intent,self.reconciliation,context); self.store.save_intent(intent); record=OrderRecord(intent); self.records[intent.intent_id]=record
        self._transition(record,OrderState.VALIDATED,context.now); self._transition(record,OrderState.SUBMITTING,context.now)
        try: broker_order_id,fills=self.adapter.place(intent)
        except PaperOrderRejected: self._transition(record,OrderState.REJECTED,context.now); return record
        if not broker_order_id: raise ExecutionBlocked("paper broker order identity is missing")
        fills=tuple(fills); seen=set(); validated=[]; total=Decimal("0")
        for fill_id,quantity,price in fills:
            quantity=_decimal(quantity,"fill quantity"); price=_decimal(price,"fill price")
            if not fill_id or fill_id in seen or self.store.fill_exists(fill_id) or price<=0 or quantity<=0 or total+quantity>intent.qty: raise ExecutionBlocked("invalid or duplicate paper fill")
            seen.add(fill_id); total+=quantity; validated.append((fill_id,quantity,price))
        record.broker_order_id=broker_order_id; self._transition(record,OrderState.ACCEPTED,context.now,broker_order_id=broker_order_id)
        for fill_id,quantity,price in validated:
            record.fill_ids.append(fill_id); record.filled_qty+=quantity; self._transition(record,OrderState.FILLED if record.filled_qty==intent.qty else OrderState.PARTIAL,context.now,fill_id=fill_id,quantity=quantity,price=price,broker_order_id=broker_order_id)
        return record
    def cancel(self, intent_id: str, at: datetime) -> OrderRecord:
        record=self.records.get(intent_id)
        if record is None or record.broker_order_id is None or record.state not in {OrderState.ACCEPTED,OrderState.PARTIAL}: raise ExecutionBlocked("order cannot be cancelled")
        self._mutation_gate(record.intent, RiskContext(at, at, record.intent.allowed_session)); self._append("CANCEL_REQUESTED",record,at,broker_order_id=record.broker_order_id); self.adapter.cancel(record.broker_order_id); self._transition(record,OrderState.CANCELLED,at,broker_order_id=record.broker_order_id); return record
    def replace(self, intent_id: str, replacement: OrderIntent, context: RiskContext) -> OrderRecord:
        record=self.records.get(intent_id)
        if record is None or record.broker_order_id is None or record.state not in {OrderState.ACCEPTED,OrderState.PARTIAL}: raise ExecutionBlocked("order cannot be replaced")
        if replacement.intent_id in self.records or self.reconciliation is None: raise ExecutionBlocked("replacement intent_id already exists or reconciliation is missing")
        self._mutation_gate(replacement,context); self.store.save_intent(replacement); self._append("REPLACE_REQUESTED",record,context.now,replaced_by=replacement.intent_id); new_broker_order_id=self.adapter.replace(record.broker_order_id,replacement); self._transition(record,OrderState.SUPERSEDED,context.now,replaced_by=replacement.intent_id)
        new_record=OrderRecord(replacement,OrderState.ACCEPTED,new_broker_order_id); self.records[replacement.intent_id]=new_record; self._append("ACCEPTED",new_record,context.now,_state=OrderState.ACCEPTED,broker_order_id=new_broker_order_id,replaces=intent_id)
        return new_record
