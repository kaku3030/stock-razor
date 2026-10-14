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


def test_release_consumes_only_remaining_reservation_after_partial_fill():
    ledger = PaperBalanceLedger(sqlite3.connect(":memory:"))
    ledger.initialize(Decimal("1000"), NOW)
    ledger.reserve("one", Decimal("300"), NOW)
    ledger.reserve("two", Decimal("400"), NOW)
    ledger.record_fill(
        fill_id="f-one", intent_id="i-one", reservation_id="one",
        symbol="AMD", side="BUY", quantity=Decimal("1"),
        price=Decimal("100"), at=NOW,
    )
    assert ledger.balance().reserved_cash == Decimal("600")
    ledger.release("one", NOW)
    assert ledger.balance().reserved_cash == Decimal("400")
    ledger.release("one", NOW)  # restart/idempotent duplicate
    assert ledger.balance().reserved_cash == Decimal("400")
    ledger.record_fill(
        fill_id="f-two", intent_id="i-two", reservation_id="two",
        symbol="AAPL", side="BUY", quantity=Decimal("1"),
        price=Decimal("400"), at=NOW,
    )
    assert ledger.balance().reserved_cash == Decimal("0")
    assert ledger.balance().cash == Decimal("500")


def test_unreserved_fill_cannot_spend_other_intents_cash():
    ledger = PaperBalanceLedger(sqlite3.connect(":memory:"))
    ledger.initialize(Decimal("1000"), NOW)
    ledger.reserve("other", Decimal("800"), NOW)
    with pytest.raises(LedgerUnknown, match="buying power"):
        ledger.record_fill(
            fill_id="f-unreserved", intent_id="unreserved", reservation_id=None,
            symbol="AMD", side="BUY", quantity=Decimal("3"),
            price=Decimal("100"), at=NOW,
        )
    assert ledger.balance().cash == Decimal("1000")
    assert ledger.balance().reserved_cash == Decimal("800")
    assert ledger.positions() == ()


def test_wrong_reservation_id_and_cross_reservation_fill_fail_closed():
    ledger = PaperBalanceLedger(sqlite3.connect(":memory:"))
    ledger.initialize(Decimal("1000"), NOW)
    ledger.reserve("small", Decimal("50"), NOW)
    ledger.reserve("large", Decimal("700"), NOW)
    for reservation in ("missing", "small"):
        with pytest.raises(LedgerUnknown, match="reservation"):
            ledger.record_fill(
                fill_id="bad-" + reservation,
                intent_id="other", reservation_id=reservation,
                symbol="AMD", side="BUY", quantity=Decimal("1"),
                price=Decimal("100"), at=NOW,
            )
    assert ledger.balance().cash == Decimal("1000")
    assert ledger.balance().reserved_cash == Decimal("750")


def test_fill_after_reservation_release_is_an_unreconciled_late_fill():
    ledger = PaperBalanceLedger(sqlite3.connect(":memory:"))
    ledger.initialize(Decimal("500"), NOW)
    ledger.reserve("cancelled", Decimal("100"), NOW)
    ledger.release("cancelled", NOW)
    with pytest.raises(LedgerUnknown, match="already released"):
        ledger.record_fill(
            fill_id="late-fill", intent_id="cancelled",
            reservation_id="cancelled", symbol="AMD", side="BUY",
            quantity=Decimal("1"), price=Decimal("100"), at=NOW,
        )
    assert ledger.balance().cash == Decimal("500")
    assert ledger.positions() == ()


def test_partial_fill_cannot_overspend_same_reservation_with_second_receipt(tmp_path):
    path = tmp_path / "paper-ledger.sqlite"
    ledger = PaperBalanceLedger(sqlite3.connect(path))
    ledger.initialize(Decimal("500"), NOW)
    ledger.reserve("order", Decimal("150"), NOW)
    ledger.record_fill(
        fill_id="first", intent_id="order", reservation_id="order",
        symbol="AMD", side="BUY", quantity=Decimal("1"),
        price=Decimal("100"), at=NOW,
    )
    with pytest.raises(LedgerUnknown, match="own reservation"):
        ledger.record_fill(
            fill_id="second", intent_id="order", reservation_id="order",
            symbol="AMD", side="BUY", quantity=Decimal("1"),
            price=Decimal("100"), at=NOW,
        )
    assert ledger.balance().reserved_cash == Decimal("50")
    ledger.connection.close()
    reopened = PaperBalanceLedger(sqlite3.connect(path))
    reopened.release("order", NOW)
    assert reopened.balance().reserved_cash == Decimal("0")
    assert reopened.balance().cash == Decimal("400")



def test_duplicate_reservation_same_amount_is_idempotent_but_conflict_blocks():
    ledger = PaperBalanceLedger(sqlite3.connect(":memory:"))
    ledger.initialize(Decimal("500"), NOW)
    first = ledger.reserve("i-one", Decimal("100.00"), NOW)
    assert ledger.reserve("i-one", Decimal("100"), NOW) == first
    with pytest.raises(LedgerUnknown, match="conflicting reservation"):
        ledger.reserve("i-one", Decimal("200"), NOW)
    assert ledger.balance() == first


def test_conflicting_duplicate_fill_receipt_is_not_silently_replayed(tmp_path):
    path = tmp_path / "receipt-conflict.sqlite"
    ledger = PaperBalanceLedger(sqlite3.connect(path))
    ledger.initialize(Decimal("500"), NOW)
    ledger.reserve("order", Decimal("300"), NOW)
    def fill(**overrides):
        params = {
            "fill_id": "same-fill", "intent_id": "order",
            "reservation_id": "order", "symbol": "AMD", "side": "BUY",
            "quantity": Decimal("1"), "price": Decimal("100"),
            "fee": Decimal("1"), "at": NOW,
        }
        params.update(overrides)
        return ledger.record_fill(**params)
    first = fill()
    assert fill(price=Decimal("100.00")) == first
    for conflict in (
        {"intent_id": "other"},
        {"reservation_id": "different"},
        {"symbol": "AAPL"},
        {"side": "SELL"},
        {"quantity": Decimal("2")},
        {"price": Decimal("101")},
        {"fee": Decimal("2")},
    ):
        with pytest.raises(LedgerUnknown, match="conflicting fill"):
            fill(**conflict)
    assert ledger.balance() == first
    ledger.connection.close()
    recovered = PaperBalanceLedger(sqlite3.connect(path))
    assert recovered.balance() == first
    assert recovered.positions()[0].qty == Decimal("1")
