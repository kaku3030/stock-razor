"""Small, durable balance ledger for offline Paper execution.

The ledger is intentionally independent from provider account read-back.  It
starts UNKNOWN and becomes KNOWN only after an explicit funding event.  No
default balance is invented.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import sqlite3
from typing import Iterable


class LedgerUnknown(RuntimeError):
    """Raised when a mutation needs a ledger that has not been initialized."""


def _decimal(value: object, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be a finite decimal")
    return result


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class LedgerBalance:
    status: str
    account_id: str
    initial_cash: Decimal | None
    cash: Decimal | None
    reserved_cash: Decimal | None
    buying_power: Decimal | None
    equity: Decimal | None
    realized_pnl: Decimal | None
    unrealized_pnl: Decimal | None
    fees: Decimal | None
    as_of: datetime | None


@dataclass(frozen=True)
class LedgerPosition:
    symbol: str
    qty: Decimal
    average_cost: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal


@dataclass(frozen=True)
class LedgerReconciliation:
    status: str
    differences: tuple[str, ...]


class PaperBalanceLedger:
    """Append-only event ledger with a materialized, recoverable projection."""

    def __init__(self, connection: sqlite3.Connection, account_id: str = "paper") -> None:
        if not account_id.strip():
            raise ValueError("account_id is required")
        self.connection = connection
        self.account_id = account_id.strip()
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS paper_ledger_accounts(
                account_id TEXT PRIMARY KEY, initial_cash TEXT NOT NULL,
                cash TEXT NOT NULL, reserved_cash TEXT NOT NULL,
                realized_pnl TEXT NOT NULL, unrealized_pnl TEXT NOT NULL,
                fees TEXT NOT NULL, as_of TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_ledger_positions(
                account_id TEXT NOT NULL, symbol TEXT NOT NULL,
                qty TEXT NOT NULL, average_cost TEXT NOT NULL,
                market_value TEXT NOT NULL, unrealized_pnl TEXT NOT NULL,
                PRIMARY KEY(account_id, symbol)
            );
            CREATE TABLE IF NOT EXISTS paper_ledger_events(
                event_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                kind TEXT NOT NULL, intent_id TEXT, fill_id TEXT,
                reservation_id TEXT, symbol TEXT, side TEXT,
                quantity TEXT, price TEXT, fee TEXT NOT NULL,
                amount TEXT, source TEXT, at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def balance(self) -> LedgerBalance:
        row = self.connection.execute(
            "SELECT initial_cash,cash,reserved_cash,realized_pnl,unrealized_pnl,fees,as_of "
            "FROM paper_ledger_accounts WHERE account_id=?", (self.account_id,)
        ).fetchone()
        if row is None:
            return LedgerBalance("UNKNOWN", self.account_id, None, None, None, None, None, None, None, None, None)
        initial, cash, reserved, realized, unrealized, fees = (Decimal(value) for value in row[:6])
        return LedgerBalance("KNOWN", self.account_id, initial, cash, reserved, cash - reserved, cash + self._market_value(), realized, unrealized, fees, datetime.fromisoformat(row[6]))

    def initialize(self, initial_cash: Decimal, at: datetime, source: str = "explicit_offline_funding") -> LedgerBalance:
        amount = _decimal(initial_cash, "initial_cash")
        if amount < 0 or not source.strip():
            raise ValueError("initial_cash must be non-negative and source is required")
        at = _utc(at)
        with self.connection:
            if self._event_exists(f"funding:{self.account_id}"):
                existing = self.balance()
                if existing.initial_cash != amount:
                    raise LedgerUnknown("conflicting funding event")
                return existing
            self.connection.execute(
                "INSERT INTO paper_ledger_accounts VALUES(?,?,?,?,?,?,?,?)",
                (self.account_id, str(amount), str(amount), "0", "0", "0", "0", at.isoformat()),
            )
            self._event("funding:" + self.account_id, "FUNDING", at, amount=amount, source=source)
        return self.balance()

    def reserve(self, reservation_id: str, amount: Decimal, at: datetime) -> LedgerBalance:
        amount = _decimal(amount, "reservation amount")
        if not reservation_id.strip() or amount <= 0:
            raise ValueError("reservation_id and positive amount are required")
        self._require_known()
        event_id = f"reserve:{reservation_id}"
        with self.connection:
            if self._event_exists(event_id):
                return self.balance()
            balance = self.balance()
            if balance.cash - balance.reserved_cash < amount:
                raise LedgerUnknown("insufficient available cash")
            self.connection.execute("UPDATE paper_ledger_accounts SET reserved_cash=?,as_of=? WHERE account_id=?", (str(balance.reserved_cash + amount), _utc(at).isoformat(), self.account_id))
            self._event(event_id, "RESERVE", at, reservation_id=reservation_id, amount=amount)
        return self.balance()

    def release(self, reservation_id: str, at: datetime) -> LedgerBalance:
        event_id = f"release:{reservation_id}"
        self._require_known()
        with self.connection:
            if self._event_exists(event_id):
                return self.balance()
            reserved = self._reservation_remaining(reservation_id)
            balance = self.balance()
            if reserved is None:
                raise LedgerUnknown("reservation is unknown")
            if reserved > balance.reserved_cash:
                raise LedgerUnknown("reservation ledger cannot cover release")
            self.connection.execute("UPDATE paper_ledger_accounts SET reserved_cash=?,as_of=? WHERE account_id=?", (str(balance.reserved_cash - reserved), _utc(at).isoformat(), self.account_id))
            self._event(event_id, "RELEASE", at, reservation_id=reservation_id, amount=reserved)
        return self.balance()

    def record_fill(self, *, fill_id: str, intent_id: str, reservation_id: str | None, symbol: str, side: str, quantity: Decimal, price: Decimal, fee: Decimal = Decimal("0"), at: datetime) -> LedgerBalance:
        self._require_known()
        quantity, price, fee = _decimal(quantity, "quantity"), _decimal(price, "price"), _decimal(fee, "fee")
        symbol, side = symbol.strip().upper(), side.strip().upper()
        if not fill_id.strip() or not intent_id.strip() or not symbol or side not in {"BUY", "SELL"} or quantity <= 0 or price <= 0 or fee < 0:
            raise ValueError("invalid fill")
        event_id = f"fill:{fill_id}"
        with self.connection:
            if self._event_exists(event_id):
                return self.balance()
            balance = self.balance()
            notional = quantity * price
            cash_delta = -notional - fee if side == "BUY" else notional - fee
            new_reserved = balance.reserved_cash
            if side == "BUY":
                amount_due = notional + fee
                if reservation_id:
                    remaining = self._reservation_remaining(reservation_id)
                    if remaining is None or self._event_exists(f"release:{reservation_id}"):
                        raise LedgerUnknown("reservation missing or already released")
                    if amount_due > remaining or amount_due > balance.reserved_cash:
                        raise LedgerUnknown("fill exceeds its own reservation")
                    new_reserved -= amount_due
                elif amount_due > balance.cash - balance.reserved_cash:
                    # Unreserved fills cannot spend another intent's cash.
                    raise LedgerUnknown("unreserved fill exceeds buying power")
                if balance.cash + cash_delta < 0:
                    raise LedgerUnknown("fill exceeds ledger cash")
            position = self._position(symbol)
            realized = Decimal("0")
            if side == "BUY":
                new_qty = position.qty + quantity
                average_cost = ((position.qty * position.average_cost) + notional) / new_qty
            else:
                if quantity > position.qty:
                    raise LedgerUnknown("sell exceeds ledger position")
                new_qty = position.qty - quantity
                average_cost = position.average_cost if new_qty else Decimal("0")
                realized = (price - position.average_cost) * quantity
            self.connection.execute("UPDATE paper_ledger_accounts SET cash=?,reserved_cash=?,realized_pnl=?,fees=?,as_of=? WHERE account_id=?", (str(balance.cash + cash_delta), str(new_reserved), str(balance.realized_pnl + realized), str(balance.fees + fee), _utc(at).isoformat(), self.account_id))
            self._save_position(symbol, new_qty, average_cost, Decimal("0"), Decimal("0"))
            self._event(event_id, "FILL", at, intent_id=intent_id, fill_id=fill_id, reservation_id=reservation_id, symbol=symbol, side=side, quantity=quantity, price=price, fee=fee)
        return self.balance()

    def mark(self, symbol: str, price: Decimal, at: datetime) -> LedgerBalance:
        price = _decimal(price, "mark price")
        if price <= 0:
            raise ValueError("mark price must be positive")
        position = self._position(symbol.strip().upper())
        if position.qty:
            self._save_position(position.symbol, position.qty, position.average_cost, position.qty * price, (price - position.average_cost) * position.qty)
        unrealized = sum((p.unrealized_pnl for p in self.positions()), Decimal("0"))
        self.connection.execute("UPDATE paper_ledger_accounts SET unrealized_pnl=?,as_of=? WHERE account_id=?", (str(unrealized), _utc(at).isoformat(), self.account_id))
        self.connection.commit()
        return self.balance()

    def positions(self) -> tuple[LedgerPosition, ...]:
        rows = self.connection.execute("SELECT symbol,qty,average_cost,market_value,unrealized_pnl FROM paper_ledger_positions WHERE account_id=? ORDER BY symbol", (self.account_id,)).fetchall()
        return tuple(LedgerPosition(r[0], *(Decimal(v) for v in r[1:])) for r in rows if Decimal(r[1]) != 0)

    def reconcile(self, cash: Decimal, positions: Iterable[LedgerPosition]) -> LedgerReconciliation:
        self._require_known()
        expected_cash = _decimal(cash, "cash")
        actual = self.balance()
        differences = []
        if actual.cash != expected_cash:
            differences.append(f"cash:{actual.cash}!={expected_cash}")
        expected = {p.symbol: p.qty for p in positions if p.qty}
        observed = {p.symbol: p.qty for p in self.positions()}
        for symbol in sorted(set(expected) | set(observed)):
            if expected.get(symbol, Decimal("0")) != observed.get(symbol, Decimal("0")):
                differences.append(f"position:{symbol}")
        return LedgerReconciliation("PASS" if not differences else "MISMATCH", tuple(differences))

    def _require_known(self) -> None:
        if self.balance().status != "KNOWN":
            raise LedgerUnknown("paper balance is UNKNOWN; explicit funding is required")

    def _market_value(self) -> Decimal:
        return sum((Decimal(row[0]) for row in self.connection.execute("SELECT market_value FROM paper_ledger_positions WHERE account_id=?", (self.account_id,))), Decimal("0"))

    def _position(self, symbol: str) -> LedgerPosition:
        row = self.connection.execute("SELECT symbol,qty,average_cost,market_value,unrealized_pnl FROM paper_ledger_positions WHERE account_id=? AND symbol=?", (self.account_id, symbol)).fetchone()
        return LedgerPosition(symbol, *(Decimal(v) for v in row[1:])) if row else LedgerPosition(symbol, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))

    def _save_position(self, symbol: str, qty: Decimal, average_cost: Decimal, market_value: Decimal, unrealized_pnl: Decimal) -> None:
        self.connection.execute("INSERT INTO paper_ledger_positions VALUES(?,?,?,?,?,?) ON CONFLICT(account_id,symbol) DO UPDATE SET qty=excluded.qty,average_cost=excluded.average_cost,market_value=excluded.market_value,unrealized_pnl=excluded.unrealized_pnl", (self.account_id, symbol, str(qty), str(average_cost), str(market_value), str(unrealized_pnl)))

    def _reservation_remaining(self, reservation_id: str) -> Decimal | None:
        """Compute this intent's unspent reservation from durable events.

        Never release another intent's funds merely because the account
        reserved_cash total is large enough. A release is terminal; an
        out-of-order later fill must reconcile as UNKNOWN before retry.
        """
        row = self.connection.execute(
            "SELECT amount FROM paper_ledger_events WHERE event_id=? AND account_id=? AND kind='RESERVE'",
            (f"reserve:{reservation_id}", self.account_id),
        ).fetchone()
        if row is None:
            return None
        original = Decimal(row[0])
        debits = self.connection.execute(
            "SELECT quantity,price,fee FROM paper_ledger_events "
            "WHERE account_id=? AND kind='FILL' AND side='BUY' AND reservation_id=?",
            (self.account_id, reservation_id),
        ).fetchall()
        consumed = sum(
            (Decimal(qty) * Decimal(price) + Decimal(fee)
             for qty, price, fee in debits),
            Decimal("0"),
        )
        remainder = original - consumed
        if remainder < 0:
            raise LedgerUnknown("reservation event ledger is inconsistent")
        return remainder

    def _event_exists(self, event_id: str) -> bool:
        return bool(self.connection.execute("SELECT 1 FROM paper_ledger_events WHERE event_id=?", (event_id,)).fetchone())

    def _event(self, event_id: str, kind: str, at: datetime, **values: object) -> None:
        self.connection.execute("INSERT INTO paper_ledger_events(event_id,account_id,kind,intent_id,fill_id,reservation_id,symbol,side,quantity,price,fee,amount,source,at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (event_id, self.account_id, kind, values.get("intent_id"), values.get("fill_id"), values.get("reservation_id"), values.get("symbol"), values.get("side"), str(values["quantity"]) if values.get("quantity") is not None else None, str(values["price"]) if values.get("price") is not None else None, str(values.get("fee", "0")), str(values["amount"]) if values.get("amount") is not None else None, values.get("source"), _utc(at).isoformat()))

