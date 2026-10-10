"""Bounded, offline Paper runtime soak and fault-injection checks."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.services.execution_engine import (
    AccountSnapshot,
    ExecutionBlocked,
    ExecutionEngine,
    ExecutionStore,
    ReconciliationSnapshot,
    RiskContext,
    RiskGuard,
    RiskLimits,
    Side,
    create_paper_adapter,
)
from src.services.paper_execution_admission import PaperOrderSpec
from src.services.paper_runtime_orchestrator import PaperRuntimeOrchestrator, PaperRuntimeState
from src.services.stock_radar_v2.observation_ledger import Observation


NOW = datetime(2026, 9, 26, 14, 30, tzinfo=timezone.utc)


def _permission(index: int, *, canonical_permission: str = "PASS") -> Observation:
    return Observation(
        observation_id=f"soak-obs-{index:03d}",
        detector_status="CONFIRMED",
        evidence_ids=(f"soak-snapshot-{index:03d}", f"soak-entry-{index:03d}"),
        strategy_gate_results={"entry_gate": "PASS"},
        strategy_eligible=True,
        portfolio_admissible=True,
        portfolio_block_reasons=(),
        execution_feasible=True,
        decision_available_at=NOW.timestamp() - 2,
        confirmed_at=NOW.timestamp() - 1,
        earliest_executable_at=NOW.timestamp() - 1,
        canonical_permission=canonical_permission,
    )


def _spec(index: int) -> PaperOrderSpec:
    return PaperOrderSpec(
        action_id=f"soak-action-{index:03d}",
        symbol="AMD",
        side=Side.BUY,
        qty=Decimal("10"),
        limit_price=Decimal("100"),
        stop_price=Decimal("97"),
        max_slippage=Decimal("0.001"),
        invalidation=Decimal("96"),
        risk_budget_r=Decimal("1"),
        strategy_id="paper-soak-v0-1",
        evidence_snapshot_id=f"soak-snapshot-{index:03d}",
        valid_until=NOW + timedelta(minutes=5),
        allowed_session="RTH",
    )


def _risk_guard() -> RiskGuard:
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


def _runtime(path, *, reconcile=None):
    capability = create_paper_adapter()
    capability.adapter.reconcile = reconcile or (
        lambda: ReconciliationSnapshot(
            AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), NOW, "paper"),
            as_of=NOW,
        )
    )
    engine = ExecutionEngine(capability, _risk_guard(), ExecutionStore(path))
    shadow_path = path.with_name(path.stem + "-shadow.sqlite")
    owner = PaperRuntimeOrchestrator(
        engine,
        runtime_generation="paper-soak-runtime",
        account_generation="paper-soak-account",
        shadow_store=ExecutionStore(shadow_path),
    )
    return owner, engine, capability.adapter


def test_three_isolated_sessions_recover_without_duplicate_placement(tmp_path):
    for index in range(1, 4):
        path = tmp_path / f"session-{index}.sqlite"
        owner, engine, adapter = _runtime(path)
        owner.start()
        result = owner.process(_permission(index), _spec(index), RiskContext(NOW, NOW, "RTH"))
        owner.stop()

        reopened, reopened_engine, reopened_adapter = _runtime(path)
        snapshot = reopened.start()

        assert snapshot.state is PaperRuntimeState.READY
        assert snapshot.journal_events == len(engine.journal)
        assert snapshot.order_records == 1
        assert reopened_engine.records[result.intent_id].broker_order_id == "paper-order-1"
        with pytest.raises(ExecutionBlocked, match="duplicate"):
            reopened.process(_permission(index), _spec(index), RiskContext(NOW, NOW, "RTH"))
        assert adapter.calls == [("place", result.intent_id)]
        assert reopened_adapter.calls == []


def test_reconciliation_failure_is_terminal_and_does_not_mutate_adapter(tmp_path):
    def fail_reconcile():
        raise RuntimeError("synthetic reconciliation failure")

    owner, _, adapter = _runtime(tmp_path / "failed.sqlite", reconcile=fail_reconcile)

    with pytest.raises(RuntimeError, match="synthetic reconciliation failure"):
        owner.start()

    assert owner.state is PaperRuntimeState.FAILED
    assert adapter.calls == []


def test_stale_data_and_unknown_permission_leave_session_ready(tmp_path):
    owner, _, adapter = _runtime(tmp_path / "negative.sqlite")
    owner.start()

    with pytest.raises(ExecutionBlocked):
        owner.process(
            _permission(1),
            _spec(1),
            RiskContext(NOW, NOW - timedelta(seconds=61), "RTH"),
        )
    with pytest.raises(ExecutionBlocked, match="permission"):
        owner.process(
            _permission(2, canonical_permission="UNKNOWN"),
            _spec(2),
            RiskContext(NOW, NOW, "RTH"),
        )

    assert owner.state is PaperRuntimeState.READY
    assert adapter.calls == []
