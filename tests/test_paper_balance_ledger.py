from datetime import datetime, timezone
from decimal import Decimal
import sqlite3

import pytest

from src.services.paper_balance_ledger import LedgerPosition, LedgerUnknown, PaperBalanceLedger


NOW = datetime(2026, 10, 14, 5, 0, tzinfo=timezone.utc)


def test_new_ledger_is_unknown_and_never_invents_starting_cash():
    ledger = PaperBalanceLedger(sqlite3.connect(":memory:"))

    balance = ledger.balance()

    assert balance.status == "UNKNOWN"
    assert balance.cash is None
    with pytest.raises(LedgerUnknown, match="explicit funding"):
        ledger.reserve("r-1", Decimal("10"), NOW)


def test_funding_reserve_fill_fee_pnl_and_valuation_are_projected():
    ledger = PaperBalanceLedger(sqlite3.connect(":memory:"))
    ledger.initialize(Decimal("1000"), NOW)
    ledger.reserve("r-1", Decimal("201"), NOW)
    ledger.record_fill(fill_id="f-1", intent_id="i-1", reservation_id="r-1", symbol="AMD", side="BUY", quantity=Decimal("2"), price=Decimal("100"), fee=Decimal("1"), at=NOW)
    ledger.mark("AMD", Decimal("110"), NOW)

    balance = ledger.balance()
    position = ledger.positions()[0]
    assert balance.cash == Decimal("799")
    assert balance.reserved_cash == Decimal("0")
    assert balance.buying_power == Decimal("799")
    assert balance.equity == Decimal("1019")
    assert balance.unrealized_pnl == Decimal("20")
    assert balance.fees == Decimal("1")
    assert position.market_value == Decimal("220")


def test_partial_fill_keeps_unfilled_cash_reserved():
    ledger = PaperBalanceLedger(sqlite3.connect(":memory:"))
    ledger.initialize(Decimal("1000"), NOW)
    ledger.reserve("r-1", Decimal("300"), NOW)
    ledger.record_fill(fill_id="f-1", intent_id="i-1", reservation_id="r-1", symbol="AMD", side="BUY", quantity=Decimal("1"), price=Decimal("100"), at=NOW)

    assert ledger.balance().cash == Decimal("900")
    assert ledger.balance().reserved_cash == Decimal("200")


def test_sell_realizes_pnl_and_fill_is_idempotent():
    ledger = PaperBalanceLedger(sqlite3.connect(":memory:"))
    ledger.initialize(Decimal("1000"), NOW)
    ledger.record_fill(fill_id="buy-1", intent_id="i-1", reservation_id=None, symbol="AMD", side="BUY", quantity=Decimal("2"), price=Decimal("100"), at=NOW)
    before = ledger.balance()
    ledger.record_fill(fill_id="buy-1", intent_id="i-1", reservation_id=None, symbol="AMD", side="BUY", quantity=Decimal("2"), price=Decimal("100"), at=NOW)
    assert ledger.balance() == before
    ledger.record_fill(fill_id="sell-1", intent_id="i-2", reservation_id=None, symbol="AMD", side="SELL", quantity=Decimal("1"), price=Decimal("120"), fee=Decimal("2"), at=NOW)

    assert ledger.balance().cash == Decimal("918")
    assert ledger.balance().realized_pnl == Decimal("20")
    assert ledger.positions()[0].qty == Decimal("1")


def test_recovery_and_reconciliation_are_deterministic(tmp_path):
    path = tmp_path / "paper-ledger.sqlite"
    first = PaperBalanceLedger(sqlite3.connect(path))
    first.initialize(Decimal("500"), NOW)
    first.record_fill(fill_id="f-1", intent_id="i-1", reservation_id=None, symbol="AAPL", side="BUY", quantity=Decimal("1"), price=Decimal("100"), at=NOW)
    first.connection.close()

    reopened = PaperBalanceLedger(sqlite3.connect(path))
    assert reopened.balance().cash == Decimal("400")
    assert reopened.reconcile(Decimal("400"), [LedgerPosition("AAPL", Decimal("1"), Decimal("100"), Decimal("0"), Decimal("0"))]).status == "PASS"
    assert reopened.reconcile(Decimal("401"), ()).status == "MISMATCH"


def test_conflicting_reinitialization_fails_closed():
    ledger = PaperBalanceLedger(sqlite3.connect(":memory:"))
    ledger.initialize(Decimal("100"), NOW)

    with pytest.raises(LedgerUnknown, match="conflicting"):
        ledger.initialize(Decimal("101"), NOW)
