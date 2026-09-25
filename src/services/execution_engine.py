"""Offline, deterministic execution-engine core.

The engine accepts validated order intents, applies a fail-closed risk guard,
and talks only to an explicitly PAPER adapter.  It has no broker SDK or
network dependency; live adapters are intentionally not supported here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Iterable, Protocol


class ExecutionBlocked(RuntimeError):
    """Raised when a safety or identity gate cannot be proven safe."""


class PaperOrderRejected(RuntimeError):
    """Deterministic paper rejection used to exercise the terminal state."""


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderState(StrEnum):
    INTENT = "INTENT"
    VALIDATED = "VALIDATED"
    SUBMITTING = "SUBMITTING"
    ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class AdapterMode(StrEnum):
    PAPER = "PAPER"


TERMINAL_STATES = frozenset({OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED})


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _decimal(value: object, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be a finite decimal")
    return result


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    symbol: str
    side: Side
    order_type: OrderType
    qty: Decimal
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    max_slippage: Decimal | None = None
    invalidation: Decimal | None = None
    risk_budget_r: Decimal | None = None
    valid_until: datetime | None = None
    strategy_id: str = ""
    evidence_snapshot_id: str = ""
    account_target: str = ""
    broker_target: str = ""
    allowed_session: str = "RTH"

    def __post_init__(self) -> None:
        if not self.intent_id.strip() or not self.symbol.strip():
            raise ValueError("intent_id and symbol are required")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        qty = _decimal(self.qty, "qty")
        if qty <= 0:
            raise ValueError("qty must be positive")
        object.__setattr__(self, "qty", qty)
        for name in ("limit_price", "stop_price", "max_slippage", "invalidation", "risk_budget_r"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _decimal(value, name))
        if self.order_type is OrderType.LIMIT and (self.limit_price is None or self.limit_price <= 0):
            raise ValueError("LIMIT intent requires a positive limit_price")
        if self.valid_until is not None:
            object.__setattr__(self, "valid_until", _utc(self.valid_until))
        if not self.strategy_id or not self.evidence_snapshot_id or not self.account_target or not self.broker_target:
            raise ValueError("strategy, evidence, account, and broker lineage are required")


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    buying_power: Decimal
    equity: Decimal
    as_of: datetime
    source: str
    fresh: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "buying_power", _decimal(self.buying_power, "buying_power"))
        object.__setattr__(self, "equity", _decimal(self.equity, "equity"))
        object.__setattr__(self, "as_of", _utc(self.as_of))


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    qty: Decimal
    market_value: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "qty", _decimal(self.qty, "position qty"))
        object.__setattr__(self, "market_value", _decimal(self.market_value, "market_value"))


@dataclass(frozen=True)
class ReconciliationSnapshot:
    account: AccountSnapshot
    positions: tuple[PositionSnapshot, ...] = ()
    open_order_ids: tuple[str, ...] = ()
    fill_ids: tuple[str, ...] = ()
    as_of: datetime | None = None
    complete: bool = True

    def __post_init__(self) -> None:
        if self.as_of is not None:
            object.__setattr__(self, "as_of", _utc(self.as_of))


@dataclass(frozen=True)
class RiskLimits:
    allowed_symbols: frozenset[str]
    max_order_notional: Decimal
    max_order_qty: Decimal
    max_symbol_exposure: Decimal
    max_portfolio_exposure: Decimal
    max_slippage: Decimal
    max_open_orders: int
    data_ttl_seconds: int
    account_ttl_seconds: int
    allowed_sessions: frozenset[str] = frozenset({"RTH"})
    daily_max_loss: Decimal = Decimal("0")


@dataclass(frozen=True)
class RiskContext:
    now: datetime
    data_as_of: datetime | None
    session: str
    kill_switch: bool = False
    daily_loss: Decimal = Decimal("0")


@dataclass(frozen=True)
class JournalEvent:
    sequence: int
    kind: str
    intent_id: str
    state: OrderState | None
    evidence_ids: tuple[str, ...]
    at: datetime
    details: tuple[tuple[str, str], ...] = ()


@dataclass
class OrderRecord:
    intent: OrderIntent
    state: OrderState = OrderState.INTENT
    broker_order_id: str | None = None
    fill_ids: list[str] = field(default_factory=list)
    filled_qty: Decimal = Decimal("0")


class BrokerAdapter(Protocol):
    mode: AdapterMode

    def place(self, intent: OrderIntent) -> tuple[str, Iterable[tuple[str, Decimal]]]: ...
    def cancel(self, broker_order_id: str) -> None: ...
    def replace(self, broker_order_id: str, intent: OrderIntent) -> None: ...
    def reconcile(self) -> ReconciliationSnapshot: ...


class PaperBrokerAdapter:
    """Deterministic adapter used by P1 tests; never opens a socket."""

    mode = AdapterMode.PAPER

    def __init__(self, fills: dict[str, tuple[tuple[str, Decimal], ...]] | None = None,
                 rejects: frozenset[str] = frozenset()) -> None:
        self._fills = fills or {}
        self._rejects = rejects
        self.calls: list[tuple[str, str]] = []
        self._next = 0

    def place(self, intent: OrderIntent) -> tuple[str, Iterable[tuple[str, Decimal]]]:
        self.calls.append(("place", intent.intent_id))
        if intent.intent_id in self._rejects:
            raise PaperOrderRejected("paper rejection")
        self._next += 1
        return f"paper-order-{self._next}", self._fills.get(intent.intent_id, ())

    def cancel(self, broker_order_id: str) -> None:
        self.calls.append(("cancel", broker_order_id))

    def replace(self, broker_order_id: str, intent: OrderIntent) -> None:
        self.calls.append(("replace", broker_order_id))

    def reconcile(self) -> ReconciliationSnapshot:
        return ReconciliationSnapshot(
            account=AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), datetime.now(timezone.utc), "paper")
        )


def _age_seconds(now: datetime, as_of: datetime | None) -> int | None:
    if as_of is None:
        return None
    return int((now - _utc(as_of)).total_seconds())


class RiskGuard:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def check(self, intent: OrderIntent, recon: ReconciliationSnapshot, context: RiskContext) -> None:
        now = _utc(context.now)
        if context.kill_switch:
            raise ExecutionBlocked("kill switch is active")
        if context.session not in self.limits.allowed_sessions or intent.allowed_session not in self.limits.allowed_sessions:
            raise ExecutionBlocked("session is not allowed")
        if intent.symbol not in {item.upper() for item in self.limits.allowed_symbols}:
            raise ExecutionBlocked("symbol is not whitelisted")
        if intent.valid_until is not None and now > intent.valid_until:
            raise ExecutionBlocked("intent is expired")
        if not recon.complete or not recon.account.fresh:
            raise ExecutionBlocked("account reconciliation is incomplete or stale")
        if _age_seconds(now, recon.account.as_of) is None or _age_seconds(now, recon.account.as_of) > self.limits.account_ttl_seconds:
            raise ExecutionBlocked("account state is stale")
        if _age_seconds(now, context.data_as_of) is None or _age_seconds(now, context.data_as_of) > self.limits.data_ttl_seconds:
            raise ExecutionBlocked("market data is stale or unknown")
        if len(recon.open_order_ids) >= self.limits.max_open_orders:
            raise ExecutionBlocked("outstanding-order cap reached")
        if intent.qty > self.limits.max_order_qty:
            raise ExecutionBlocked("order quantity exceeds limit")
        reference = intent.limit_price
        if reference is None:
            raise ExecutionBlocked("paper V0.1 requires a limit reference price")
        notional = intent.qty * reference
        if notional > self.limits.max_order_notional:
            raise ExecutionBlocked("order notional exceeds limit")
        if intent.max_slippage is None or intent.max_slippage > self.limits.max_slippage:
            raise ExecutionBlocked("slippage budget is missing or exceeds limit")
        if self.limits.daily_max_loss > 0 and context.daily_loss >= self.limits.daily_max_loss:
            raise ExecutionBlocked("daily loss limit reached")
        current_symbol = next((p.market_value for p in recon.positions if p.symbol == intent.symbol), Decimal("0"))
        if current_symbol + notional > self.limits.max_symbol_exposure:
            raise ExecutionBlocked("symbol exposure exceeds limit")
        portfolio = sum((p.market_value for p in recon.positions), Decimal("0"))
        if portfolio + notional > self.limits.max_portfolio_exposure:
            raise ExecutionBlocked("portfolio exposure exceeds limit")


class ExecutionEngine:
    def __init__(self, adapter: BrokerAdapter, risk_guard: RiskGuard) -> None:
        if getattr(adapter, "mode", None) is not AdapterMode.PAPER:
            raise ExecutionBlocked("non-paper adapters are disabled in V0.1")
        self.adapter = adapter
        self.risk_guard = risk_guard
        self.records: dict[str, OrderRecord] = {}
        self.journal: tuple[JournalEvent, ...] = ()
        self.reconciliation: ReconciliationSnapshot | None = None

    def _append(self, kind: str, record: OrderRecord, at: datetime, **details: object) -> None:
        self.journal += (JournalEvent(len(self.journal) + 1, kind, record.intent.intent_id, record.state,
                                      (record.intent.evidence_snapshot_id, *record.fill_ids), _utc(at),
                                      tuple(sorted((str(k), str(v)) for k, v in details.items()))),)

    def reconcile(self) -> ReconciliationSnapshot:
        snapshot = self.adapter.reconcile()
        if not snapshot.complete or not snapshot.account.fresh:
            self.reconciliation = snapshot
            raise ExecutionBlocked("reconciliation is incomplete or stale")
        self.reconciliation = snapshot
        return snapshot

    def submit(self, intent: OrderIntent, context: RiskContext) -> OrderRecord:
        if intent.intent_id in self.records:
            raise ExecutionBlocked("duplicate intent_id")
        if self.reconciliation is None:
            raise ExecutionBlocked("startup reconciliation is required")
        self.risk_guard.check(intent, self.reconciliation, context)
        record = OrderRecord(intent=intent, state=OrderState.VALIDATED)
        self.records[intent.intent_id] = record
        self._append("VALIDATED", record, context.now)
        record.state = OrderState.SUBMITTING
        self._append("SUBMITTING", record, context.now)
        try:
            broker_order_id, fills = self.adapter.place(intent)
        except PaperOrderRejected:
            record.state = OrderState.REJECTED
            self._append("REJECTED", record, context.now)
            return record
        record.broker_order_id = broker_order_id
        record.state = OrderState.ACCEPTED
        self._append("ACCEPTED", record, context.now, broker_order_id=broker_order_id)
        for fill_id, quantity in fills:
            if quantity <= 0 or record.filled_qty + quantity > intent.qty:
                raise ExecutionBlocked("invalid paper fill")
            record.fill_ids.append(fill_id)
            record.filled_qty += quantity
            record.state = OrderState.FILLED if record.filled_qty == intent.qty else OrderState.PARTIAL
            self._append("FILL", record, context.now, fill_id=fill_id, quantity=quantity)
        return record

    def cancel(self, intent_id: str, at: datetime) -> OrderRecord:
        record = self.records.get(intent_id)
        if record is None or record.broker_order_id is None:
            raise ExecutionBlocked("unknown order identity")
        if record.state in TERMINAL_STATES:
            raise ExecutionBlocked("terminal order cannot be cancelled")
        self.adapter.cancel(record.broker_order_id)
        record.state = OrderState.CANCELLED
        self._append("CANCELLED", record, at, broker_order_id=record.broker_order_id)
        return record

    def replace(self, intent_id: str, replacement: OrderIntent, context: RiskContext) -> OrderRecord:
        record = self.records.get(intent_id)
        if record is None or record.broker_order_id is None or record.state in TERMINAL_STATES:
            raise ExecutionBlocked("order cannot be replaced")
        if replacement.intent_id in self.records:
            raise ExecutionBlocked("replacement intent_id already exists")
        if self.reconciliation is None:
            raise ExecutionBlocked("reconciliation is required")
        self.risk_guard.check(replacement, self.reconciliation, context)
        self.adapter.replace(record.broker_order_id, replacement)
        self.records[replacement.intent_id] = OrderRecord(replacement, OrderState.ACCEPTED, record.broker_order_id)
        self._append("REPLACED", self.records[replacement.intent_id], context.now, replaced_intent_id=intent_id)
        return self.records[replacement.intent_id]
