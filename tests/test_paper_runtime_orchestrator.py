from datetime import datetime, timedelta, timezone
from decimal import Decimal
import threading

import pytest

from src.services.execution_engine import (
    AccountSnapshot,
    ExecutionBlocked,
    ExecutionEngine,
    ExecutionStore,
    OrderState,
    ReconciliationSnapshot,
    RiskContext,
    RiskGuard,
    RiskLimits,
    Side,
    create_paper_adapter,
)
from src.services.paper_execution_admission import PaperOrderSpec
from src.services.paper_runtime_orchestrator import (
    PaperRuntimeOrchestrator,
    PaperRuntimeState,
)
from src.services.stock_radar_v2.observation_ledger import Observation


NOW = datetime(2026, 9, 26, 14, 30, tzinfo=timezone.utc)


def permission(index=1, **changes):
    values = {
        "observation_id": f"obs-amd-{index:03d}",
        "detector_status": "CONFIRMED",
        "evidence_ids": (f"snapshot-amd-{index:03d}", f"entry-amd-{index:03d}"),
        "strategy_gate_results": {"entry_gate": "PASS"},
        "strategy_eligible": True,
        "portfolio_admissible": True,
        "portfolio_block_reasons": (),
        "execution_feasible": True,
        "decision_available_at": NOW.timestamp() - 2,
        "confirmed_at": NOW.timestamp() - 1,
        "earliest_executable_at": NOW.timestamp() - 1,
        "canonical_permission": "PASS",
    }
    values.update(changes)
    return Observation(**values)


def spec(index=1, **changes):
    values = {
        "action_id": f"action-amd-{index:03d}",
        "symbol": "AMD",
        "side": Side.BUY,
        "qty": Decimal("10"),
        "limit_price": Decimal("100"),
        "stop_price": Decimal("97"),
        "max_slippage": Decimal("0.001"),
        "invalidation": Decimal("96"),
        "risk_budget_r": Decimal("1"),
        "strategy_id": "paper-runtime-v0-1",
        "evidence_snapshot_id": f"snapshot-amd-{index:03d}",
        "valid_until": NOW + timedelta(minutes=5),
        "allowed_session": "RTH",
    }
    values.update(changes)
    return PaperOrderSpec(**values)


def risk_guard():
    return RiskGuard(
        RiskLimits(
            frozenset({"AMD"}),
            Decimal("5000"),
            Decimal("100"),
            Decimal("10000"),
            Decimal("20000"),
            Decimal("0.01"),
            10,
            60,
            60,
        )
    )


def runtime(tmp_path, fills=None):
    capability = create_paper_adapter(fills=fills)
    capability.adapter.reconcile = lambda: ReconciliationSnapshot(
        AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), NOW, "paper"),
        as_of=NOW,
    )
    engine = ExecutionEngine(
        capability, risk_guard(), ExecutionStore(tmp_path / "runtime.sqlite")
    )
    owner = PaperRuntimeOrchestrator(
        engine,
        runtime_generation="paper-runtime-generation-1",
        account_generation="paper-account-generation-1",
    )
    return owner, engine, capability.adapter


def context(**changes):
    values = {
        "now": NOW,
        "data_as_of": NOW,
        "session": "RTH",
    }
    values.update(changes)
    return RiskContext(**values)


def test_startup_reconciliation_barrier_runs_before_ready(tmp_path):
    owner, engine, adapter = runtime(tmp_path)
    called = []
    original = adapter.reconcile

    def reconcile():
        called.append("reconcile")
        return original()

    adapter.reconcile = reconcile

    snapshot = owner.start()

    assert called == ["reconcile"]
    assert owner.state is PaperRuntimeState.READY
    assert engine.reconciliation is not None
    assert snapshot.state is PaperRuntimeState.READY
    assert snapshot.reconciliation_as_of is not None


def test_process_before_start_is_blocked_without_paper_mutation(tmp_path):
    owner, _, adapter = runtime(tmp_path)

    with pytest.raises(ExecutionBlocked, match="not READY"):
        owner.process(permission(), spec(), context())

    assert adapter.calls == []


def test_explicit_permission_flows_through_shadow_and_paper_execution(tmp_path):
    first_intent_id = "placeholder"
    owner, _, adapter = runtime(tmp_path)
    owner.start()

    # Use deterministic fill ids while letting the adapter key be installed after
    # admission by matching the stable action identity through a first dry build in
    # the dedicated admission tests. Here an empty fill set still proves ACCEPTED.
    result = owner.process(permission(), spec(), context())

    assert result.runtime_generation == "paper-runtime-generation-1"
    assert result.intent_id != first_intent_id
    assert result.shadow_decision_id
    assert result.order_state is OrderState.ACCEPTED
    assert result.broker_order_id == "paper-order-1"
    assert result.fill_ids == ()
    assert adapter.calls == [("place", result.intent_id)]


def test_duplicate_retry_same_action_is_blocked_without_second_place(tmp_path):
    owner, _, adapter = runtime(tmp_path)
    owner.start()
    first = owner.process(permission(), spec(), context())

    with pytest.raises(ExecutionBlocked, match="duplicate"):
        owner.process(permission(), spec(qty=Decimal("5"), limit_price=Decimal("99")), context())

    assert adapter.calls == [("place", first.intent_id)]
    assert owner.state is PaperRuntimeState.READY


def test_stale_market_is_blocked_before_paper_adapter_and_runtime_stays_ready(tmp_path):
    owner, _, adapter = runtime(tmp_path)
    owner.start()

    with pytest.raises(ExecutionBlocked):
        owner.process(
            permission(2),
            spec(2),
            context(data_as_of=NOW - timedelta(seconds=61)),
        )

    assert adapter.calls == []
    assert owner.state is PaperRuntimeState.READY


def test_unknown_permission_is_blocked_before_shadow_or_paper_mutation(tmp_path):
    owner, _, adapter = runtime(tmp_path)
    owner.start()

    with pytest.raises(ExecutionBlocked, match="permission"):
        owner.process(
            permission(3, canonical_permission="UNKNOWN"),
            spec(3),
            context(),
        )

    assert adapter.calls == []
    assert owner.state is PaperRuntimeState.READY


def test_reconciliation_failure_fails_runtime_closed(tmp_path):
    owner, engine, adapter = runtime(tmp_path)

    def broken_reconcile():
        raise ExecutionBlocked("reconciliation unavailable")

    adapter.reconcile = broken_reconcile

    with pytest.raises(ExecutionBlocked, match="unavailable"):
        owner.start()

    assert owner.state is PaperRuntimeState.FAILED
    assert engine.reconciliation is None
    with pytest.raises(ExecutionBlocked, match="only start from NEW"):
        owner.start()


def test_unexpected_adapter_failure_marks_runtime_failed_and_blocks_future_work(tmp_path):
    owner, _, adapter = runtime(tmp_path)
    owner.start()

    def crash_place(_intent):
        raise ValueError("unexpected adapter failure")

    adapter.place = crash_place

    with pytest.raises(ValueError, match="unexpected"):
        owner.process(permission(4), spec(4), context())

    assert owner.state is PaperRuntimeState.FAILED
    with pytest.raises(ExecutionBlocked, match="not READY"):
        owner.process(permission(5), spec(5), context())


def test_refresh_reconciliation_updates_generation_and_allows_fresh_context(tmp_path):
    owner, engine, adapter = runtime(tmp_path)
    owner.start()
    later = NOW + timedelta(seconds=30)
    adapter.reconcile = lambda: ReconciliationSnapshot(
        AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), later, "paper"),
        as_of=later,
    )

    snapshot = owner.refresh_reconciliation(account_generation="paper-account-generation-2")

    assert snapshot.account_generation == "paper-account-generation-2"
    assert snapshot.reconciliation_as_of == later
    result = owner.process(
        permission(8),
        spec(8),
        RiskContext(later, later, "RTH"),
    )
    assert result.order_state is OrderState.ACCEPTED


def test_cancel_routes_through_existing_execution_engine(tmp_path):
    owner, _, adapter = runtime(tmp_path)
    owner.start()
    opened = owner.process(permission(9), spec(9), context())

    cancelled = owner.cancel(opened.intent_id, at=NOW)

    assert cancelled.order_state is OrderState.CANCELLED
    assert adapter.calls == [
        ("place", opened.intent_id),
        ("cancel", opened.broker_order_id),
    ]


def test_replace_requires_new_permission_and_preserves_execution_lineage(tmp_path):
    owner, _, adapter = runtime(tmp_path)
    owner.start()
    opened = owner.process(permission(10), spec(10), context())

    replaced = owner.replace(
        opened.intent_id,
        permission(11),
        spec(11, qty=Decimal("5"), limit_price=Decimal("99")),
        context(),
    )

    assert replaced.intent_id != opened.intent_id
    assert replaced.order_state is OrderState.ACCEPTED
    assert replaced.shadow_decision_id
    assert adapter.calls == [
        ("place", opened.intent_id),
        ("replace", opened.broker_order_id),
    ]


def test_replace_unknown_permission_is_blocked_before_adapter_mutation(tmp_path):
    owner, _, adapter = runtime(tmp_path)
    owner.start()
    opened = owner.process(permission(12), spec(12), context())
    before = list(adapter.calls)

    with pytest.raises(ExecutionBlocked, match="permission"):
        owner.replace(
            opened.intent_id,
            permission(13, canonical_permission="UNKNOWN"),
            spec(13),
            context(),
        )

    assert adapter.calls == before
    assert owner.state is PaperRuntimeState.READY


def test_non_owner_thread_is_fail_closed_and_owner_thread_remains_single_writer(tmp_path):
    owner, _, adapter = runtime(tmp_path)
    owner.start()
    errors = []

    def worker():
        try:
            owner.process(permission(6), spec(6), context())
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert len(errors) == 1
    assert isinstance(errors[0], ExecutionBlocked)
    assert "single-writer owner thread" in str(errors[0])
    assert adapter.calls == []

    result = owner.process(permission(6), spec(6), context())
    assert adapter.calls == [("place", result.intent_id)]
    assert owner.state is PaperRuntimeState.READY


def test_stop_is_idempotent_and_prevents_new_work(tmp_path):
    owner, _, adapter = runtime(tmp_path)
    owner.start()

    first = owner.stop()
    second = owner.stop()

    assert first.state is PaperRuntimeState.STOPPED
    assert second.state is PaperRuntimeState.STOPPED
    with pytest.raises(ExecutionBlocked, match="not READY"):
        owner.process(permission(7), spec(7), context())
    assert adapter.calls == []


def test_runtime_module_has_no_live_broker_or_network_surface():
    import src.services.paper_runtime_orchestrator as module

    public = {name for name in dir(module) if not name.startswith("_")}
    assert "PaperRuntimeOrchestrator" in public
    assert not any(
        name in public
        for name in (
            "socket",
            "requests",
            "httpx",
            "alpaca",
            "futu",
            "moomoo",
            "OpenD",
        )
    )
