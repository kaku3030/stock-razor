from dataclasses import replace
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
    create_paper_adapter,
    PositionSnapshot,
    ReconciliationSnapshot,
    ExecutionStore,
    JournalEvent,
    ResourceSnapshot,
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
    capability = create_paper_adapter(fills=fills)
    adapter = capability.adapter
    limits = RiskLimits(frozenset({"AMD"}), Decimal("5000"), Decimal("100"),
                        Decimal("10000"), Decimal("20000"), Decimal("0.01"), 10, 60, 60)
    result = ExecutionEngine(capability, RiskGuard(limits))
    result.reconciliation = ReconciliationSnapshot(
        AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), NOW, "paper"),
        tuple(positions), tuple(open_orders), as_of=NOW)
    return result, adapter


def context(data_as_of=NOW, kill_switch=False, session="RTH", daily_loss=Decimal("0")):
    return RiskContext(NOW, data_as_of, session, kill_switch=kill_switch, daily_loss=daily_loss)


def test_normal_partial_fill_and_completion_are_auditable():
    e, adapter = engine({"i-1": (("f-1", Decimal("4"), Decimal("100")), ("f-2", Decimal("6"), Decimal("100")))})
    record = e.submit(intent(), context())
    assert record.state is OrderState.FILLED
    assert record.broker_order_id == "paper-order-1"
    assert record.fill_ids == ["f-1", "f-2"]
    assert [event.kind for event in e.journal] == ["VALIDATED", "SUBMITTING", "ACCEPTED", "PARTIAL", "FILLED"]
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

    with pytest.raises(ExecutionBlocked, match="factory-issued"):
        ExecutionEngine(LiveLike(), RiskGuard(RiskLimits(frozenset(), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("0"), 1, 1, 1)))


def test_intent_requires_lineage_and_timezone():
    with pytest.raises(ValueError):
        OrderIntent("i", "AMD", Side.BUY, OrderType.LIMIT, Decimal("1"), limit_price=Decimal("1"))
    with pytest.raises(ValueError):
        intent(). __class__("i", "AMD", Side.BUY, OrderType.LIMIT, Decimal("1"), limit_price=Decimal("1"),
                            valid_until=datetime(2026, 9, 25), strategy_id="s", evidence_snapshot_id="e", account_target="a", broker_target="b")


def test_persistent_store_replays_and_blocks_duplicate_after_restart(tmp_path):
    path = tmp_path / "execution.sqlite"
    e, _ = engine()
    store = ExecutionStore(path)
    capability = create_paper_adapter()
    limits = e.risk_guard
    first = ExecutionEngine(capability, limits, store)
    first.reconciliation = e.reconciliation
    first.submit(intent(), context())
    reopened = ExecutionEngine(create_paper_adapter(), limits, ExecutionStore(path))
    assert [event.kind for event in reopened.journal] == ["VALIDATED", "SUBMITTING", "ACCEPTED"]
    reopened.reconciliation = e.reconciliation
    with pytest.raises(ExecutionBlocked, match="duplicate"):
        reopened.submit(intent(), context())


def test_resource_freshness_and_identity_are_all_fail_closed():
    e, adapter = engine()
    stale = ResourceSnapshot("paper", "paper", NOW - timedelta(seconds=61), fresh=False)
    e.reconciliation = ReconciliationSnapshot(e.reconciliation.account, as_of=NOW,
                                               funds=stale)
    with pytest.raises(ExecutionBlocked, match="reconciliation"):
        e.submit(intent(), context())
    e.reconciliation = ReconciliationSnapshot(AccountSnapshot("other", Decimal("100000"), Decimal("100000"), NOW, "paper"), as_of=NOW)
    with pytest.raises(ExecutionBlocked, match="identity"):
        e.submit(intent(), context())
    assert adapter.calls == []


def test_insufficient_buying_power_and_duplicate_fill_are_blocked():
    e, adapter = engine({"i-1": (("f-1", Decimal("10"), Decimal("100")),)})
    e.reconciliation = ReconciliationSnapshot(AccountSnapshot("paper", Decimal("1"), Decimal("1"), NOW, "paper"), as_of=NOW)
    with pytest.raises(ExecutionBlocked, match="buying power"):
        e.submit(intent(), context())
    assert adapter.calls == []


def test_invalid_fill_price_is_blocked_after_acceptance():
    e, _ = engine({"i-1": (("f-1", Decimal("1"), Decimal("0")),)})
    with pytest.raises(ExecutionBlocked, match="invalid or duplicate paper fill"):
        e.submit(intent(), context())


def test_reconciliation_overall_timestamp_and_each_resource_identity_are_required():
    e, adapter = engine()
    e.reconciliation = ReconciliationSnapshot(e.reconciliation.account, as_of=None)
    with pytest.raises(ExecutionBlocked, match="reconciliation"):
        e.submit(intent(), context())
    e.reconciliation = ReconciliationSnapshot(
        e.reconciliation.account, as_of=NOW,
        funds=ResourceSnapshot("other", "paper", NOW),
    )
    with pytest.raises(ExecutionBlocked, match="reconciliation"):
        e.submit(intent(), context())
    assert adapter.calls == []


def test_all_fill_validation_is_atomic_before_acceptance():
    e, adapter = engine({"i-1": (("f-1", Decimal("4"), Decimal("100")), ("f-1", Decimal("6"), Decimal("100")))})
    with pytest.raises(ExecutionBlocked, match="invalid or duplicate"):
        e.submit(intent(), context())
    assert adapter.calls == [("place", "i-1")]
    assert [event.kind for event in e.journal] == ["VALIDATED", "SUBMITTING"]


def test_restart_with_submitting_or_pending_cancel_is_blocked(tmp_path):
    path = tmp_path / "ambiguous.sqlite"
    store = ExecutionStore(path)
    candidate = intent()
    store.save_intent(candidate)
    store.append(JournalEvent(1, "SUBMITTING", candidate.intent_id, OrderState.SUBMITTING, ("evidence",), NOW))
    with pytest.raises(ExecutionBlocked, match="ambiguous"):
        ExecutionEngine(create_paper_adapter(), engine()[0].risk_guard, ExecutionStore(path))


def test_journal_and_intents_are_immutable(tmp_path):
    store = ExecutionStore(tmp_path / "immutable.sqlite")
    candidate = intent()
    store.save_intent(candidate)
    store.append(JournalEvent(1, "NOTE", candidate.intent_id, None, ("evidence",), NOW))
    with pytest.raises(Exception, match="append-only"):
        store.connection.execute("UPDATE events SET kind='CHANGED' WHERE sequence=1")
    with pytest.raises(Exception, match="append-only"):
        store.connection.execute("DELETE FROM events WHERE sequence=1")
    with pytest.raises(Exception, match="immutable"):
        store.connection.execute("UPDATE intents SET payload='{}' WHERE intent_id='i-1'")


def test_factory_capability_cannot_be_forged_by_mode_shape():
    from src.services import execution_engine as module
    with pytest.raises(ExecutionBlocked, match="factory"):
        module._PaperCapability(module.PaperBrokerAdapter(), object())


def test_cancel_requires_current_reconciliation_before_adapter_mutation():
    e, adapter = engine()
    e.submit(intent(), context())
    e.reconciliation = ReconciliationSnapshot(
        AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), NOW, "paper"),
        as_of=NOW, funds=ResourceSnapshot("paper", "paper", NOW, fresh=False),
    )
    with pytest.raises(ExecutionBlocked, match="reconciliation"):
        e.cancel("i-1", NOW)
    assert adapter.calls == [("place", "i-1")]


def test_successful_replace_is_terminal_with_supersession_lineage():
    e, adapter = engine()
    e.submit(intent(), context())
    replacement = intent("i-2", qty="5")
    result = e.replace("i-1", replacement, context())
    assert result.state is OrderState.ACCEPTED
    assert result.broker_order_id == "paper-order-2"
    assert e.records["i-1"].state is OrderState.SUPERSEDED
    assert adapter.calls == [("place", "i-1"), ("replace", "paper-order-1")]
    assert dict(e.journal[-1].details)["replaces"] == "i-1"


def test_remaining_risk_matrix_rejects_before_any_adapter_mutation():
    base_limits = RiskLimits(frozenset({"AMD"}), Decimal("5000"), Decimal("100"), Decimal("10000"), Decimal("20000"), Decimal("0.01"), 10, 60, 60)
    cases = [
        (replace(base_limits, daily_max_loss=Decimal("10")), intent(), context(daily_loss=Decimal("10")), None),
        (replace(base_limits, max_order_notional=Decimal("500")), intent(), context(), None),
        (replace(base_limits, max_symbol_exposure=Decimal("50")), intent(), context(), None),
        (replace(base_limits, max_portfolio_exposure=Decimal("50")), intent(), context(), None),
        (replace(base_limits, allowed_sessions=frozenset({"RTH"})), intent(), context(session="AH"), None),
        (replace(base_limits, max_slippage=Decimal("0.0001")), intent(), context(), None),
        (replace(base_limits, max_open_orders=0), intent(), context(), ReconciliationSnapshot(AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), NOW, "paper"), open_order_ids=("existing",), as_of=NOW)),
        (base_limits, intent(symbol="QQQ"), context(), None),
        (base_limits, intent(), context(), ReconciliationSnapshot(AccountSnapshot("paper", Decimal("1"), Decimal("1"), NOW, "paper"), as_of=NOW)),
    ]
    for limits, candidate, candidate_context, reconciliation in cases:
        e, adapter = engine()
        e.risk_guard.limits = limits
        if reconciliation is not None:
            e.reconciliation = reconciliation
        with pytest.raises(ExecutionBlocked):
            e.submit(candidate, candidate_context)
        assert adapter.calls == []
