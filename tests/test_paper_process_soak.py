"""OS-process boundary soak checks for the paper-only runtime.

These tests use only the deterministic paper adapter. They intentionally launch
a child interpreter so SQLite durability is checked across process termination,
not only across object reconstruction.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys

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
from src.services.paper_runtime_orchestrator import PaperRuntimeOrchestrator
from src.services.stock_radar_v2.observation_ledger import Observation


NOW = datetime(2026, 9, 26, 14, 30, tzinfo=timezone.utc)


def _permission() -> Observation:
    return Observation(
        observation_id="process-soak-obs-001",
        detector_status="CONFIRMED",
        evidence_ids=("process-soak-snapshot-001", "process-soak-entry-001"),
        strategy_gate_results={"entry_gate": "PASS"},
        strategy_eligible=True,
        portfolio_admissible=True,
        portfolio_block_reasons=(),
        execution_feasible=True,
        decision_available_at=NOW.timestamp() - 2,
        confirmed_at=NOW.timestamp() - 1,
        earliest_executable_at=NOW.timestamp() - 1,
        canonical_permission="PASS",
    )


def _spec() -> PaperOrderSpec:
    return PaperOrderSpec(
        action_id="process-soak-action-001",
        symbol="AMD",
        side=Side.BUY,
        qty=Decimal("10"),
        limit_price=Decimal("100"),
        stop_price=Decimal("97"),
        max_slippage=Decimal("0.001"),
        invalidation=Decimal("96"),
        risk_budget_r=Decimal("1"),
        strategy_id="paper-process-soak-v0-1",
        evidence_snapshot_id="process-soak-snapshot-001",
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


def _reconcile() -> ReconciliationSnapshot:
    return ReconciliationSnapshot(
        AccountSnapshot("paper", Decimal("100000"), Decimal("100000"), NOW, "paper"),
        as_of=NOW,
    )


def _runtime(runtime_path: Path, shadow_path: Path, *, crash_on_submit: bool = False):
    capability = create_paper_adapter()
    capability.adapter.reconcile = _reconcile
    if crash_on_submit:
        def crash(_intent):
            os._exit(73)

        capability.adapter.place = crash
    engine = ExecutionEngine(capability, _risk_guard(), ExecutionStore(runtime_path))
    owner = PaperRuntimeOrchestrator(
        engine,
        runtime_generation="paper-process-runtime",
        account_generation="paper-process-account",
        shadow_store=ExecutionStore(shadow_path),
    )
    return owner


def _child(mode: str, runtime_path: Path, shadow_path: Path) -> int:
    owner = _runtime(
        runtime_path,
        shadow_path,
        crash_on_submit=mode == "crash-after-shadow",
    )
    owner.start()
    if mode == "blocked":
        try:
            owner.process(
                _permission(),
                _spec(),
                RiskContext(NOW, NOW - timedelta(seconds=61), "RTH"),
            )
        except ExecutionBlocked:
            return 0
        return 2
    owner.process(_permission(), _spec(), RiskContext(NOW, NOW, "RTH"))
    return 2


def _run_child(mode: str, runtime_path: Path, shadow_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--child",
            mode,
            str(runtime_path),
            str(shadow_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        },
        text=True,
        capture_output=True,
        check=False,
    )


def test_blocked_shadow_evidence_survives_real_process_exit(tmp_path):
    runtime_path = tmp_path / "runtime.sqlite"
    shadow_path = tmp_path / "shadow.sqlite"

    child = _run_child("blocked", runtime_path, shadow_path)

    assert child.returncode == 0, child.stderr
    assert len(ExecutionStore(shadow_path).events()) == 1
    assert ExecutionStore(runtime_path).events() == []


def test_crash_after_shadow_before_submit_is_ambiguous_and_not_success(tmp_path):
    runtime_path = tmp_path / "runtime.sqlite"
    shadow_path = tmp_path / "shadow.sqlite"

    child = _run_child("crash-after-shadow", runtime_path, shadow_path)

    assert child.returncode == 73
    assert len(ExecutionStore(shadow_path).events()) == 1
    runtime_events = ExecutionStore(runtime_path).events()
    assert [event.kind for event in runtime_events] == ["VALIDATED", "SUBMITTING"]
    assert not any(event.kind in {"ACCEPTED", "FILLED"} for event in runtime_events)
    assert not list(tmp_path.glob("*.broker-success"))


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--child":
        raise SystemExit("child mode required")
    raise SystemExit(_child(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])))
