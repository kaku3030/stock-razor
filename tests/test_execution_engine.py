from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.services.execution_engine import (
    AccountSnapshot,
    AdapterMode,
    ExecutionBlocked,
    ExecutionEngine,
    OrderIntent,
    OrderState,
    OrderType,
    PaperBrokerAdapter,
    PositionSnapshot,
    ReconciliationSnapshot,
    RiskContext,
    RiskGuard,
    RiskLimits,
    Side,
)


NOW = datetime(2026, 9, 25, 1, 0, tzinfo=timezone.utc)


def intent(intent_id="i-1", symbol="AMD", qty="10"):
    return OrderIntent(intent_id, symbol, Side.BUY, OrderType.LIMIT, Decimal(qty),
                       limit_price=Decimal("100"), max_slippage=Decimal("0.001"),
                       strategy_id="strategy", evidence_snapshot_id="evidence",
                       account_target="paper", broker_target="paper")


def engine(fills=None, positions=(), open_orders=()):
    adapter = PaperBrokerAdapter(fills)
    limits = RiskLimits(frozenset({"AMD"}), Decimal("5000"), Decimal("100"),
                        Decimal("10000"), Decimal("20000"), Decimal("0.01"), 10, 60, 60)
    result = ExecutionEngine(adapter, RiskGuard(limits))
    result.reconciliation = ReconciliationSnapshot(
        AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), NOW, "paper"),
        tuple(positions), tuple(open_orders), NOW)
    return result, adapter


def context(data_as_of=NOW, kill_switch=False):
    return RiskContext(NOW, data_as_of, "RTH", kill_switch=kill_switch)


def test_normal_partial_fill_and_completion_are_auditable():
    e, adapter = engine({"i-1": (("f-1", Decimal("4")), ("f-2", Decimal("6")))})
    record = e.submit(intent(), context())
    assert record.state is OrderState.FILLED
    assert record.broker_order_id == "paper-order-1"
    assert record.fill_ids == ["f-1", "f-2"]
    assert [event.kind for event in e.journal] == ["VALIDATED", "SUBMITTING", "ACCEPTED", "FILL", "FILL"]
    assert adapter.calls == [("place", "i-1")]


def test_duplicate_intent_is_fail_closed_without_second_place():
    e, adapter = engine()
    e.submit(intent(), context())
    with pytest.raises(ExecutionBlocked, match="duplicate"):
        e.submit(intent(), context())
    assert [call for call in adapter.calls if call[0] == "place"] == [("place", "i-1")]


@pytest.mark.parametrize("change", [
    {"kill_switch": True},
    {"data_as_of": NOW - timedelta(seconds=61)},
    {"symbol": "QQQ"},
    {"qty": "101"},
])
def test_risk_breaches_fail_closed(change):
    e, adapter = engine()
    kwargs = {"data_as_of": NOW}
    if "kill_switch" in change:
        kwargs["kill_switch"] = change["kill_switch"]
    if "data_as_of" in change:
        kwargs["data_as_of"] = change["data_as_of"]
    candidate = intent(symbol=change.get("symbol", "AMD"), qty=change.get("qty", "10"))
    with pytest.raises(ExecutionBlocked):
        e.submit(candidate, context(**kwargs))
    assert adapter.calls == []


def test_stale_account_or_incomplete_reconciliation_blocks():
    e, adapter = engine()
    e.reconciliation = ReconciliationSnapshot(
        AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), NOW - timedelta(seconds=61), "paper"),
        complete=False)
    with pytest.raises(ExecutionBlocked):
        e.submit(intent(), context())
    assert adapter.calls == []


def test_cancel_and_replace_race_boundary_is_terminal_and_auditable():
    e, adapter = engine()
    e.submit(intent(), context())
    e.cancel("i-1", NOW)
    with pytest.raises(ExecutionBlocked):
        e.replace("i-1", intent("i-2"), context())
    assert adapter.calls == [("place", "i-1"), ("cancel", "paper-order-1")]
    assert e.records["i-1"].state is OrderState.CANCELLED


def test_paper_reject_is_terminal_and_never_claims_acceptance():
    e, adapter = engine()
    adapter._rejects = frozenset({"i-1"})
    record = e.submit(intent(), context())
    assert record.state is OrderState.REJECTED
    assert [event.kind for event in e.journal] == ["VALIDATED", "SUBMITTING", "REJECTED"]


def test_non_paper_adapter_is_hard_blocked():
    class LiveLike:
        mode = "LIVE"

    with pytest.raises(ExecutionBlocked, match="non-paper"):
        ExecutionEngine(LiveLike(), RiskGuard(RiskLimits(frozenset(), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("0"), 1, 1, 1)))


def test_intent_requires_lineage_and_timezone():
    with pytest.raises(ValueError):
        OrderIntent("i", "AMD", Side.BUY, OrderType.LIMIT, Decimal("1"), limit_price=Decimal("1"))
    with pytest.raises(ValueError):
        intent(). __class__("i", "AMD", Side.BUY, OrderType.LIMIT, Decimal("1"), limit_price=Decimal("1"),
                            valid_until=datetime(2026, 9, 25), strategy_id="s", evidence_snapshot_id="e", account_target="a", broker_target="b")
