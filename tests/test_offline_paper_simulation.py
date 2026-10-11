from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.services.execution_engine import (
    RiskContext,
    RiskGuard,
    RiskLimits,
    Side,
    create_paper_adapter,
)
from src.services.offline_paper_simulation import run_offline_paper_simulation
from src.services.paper_execution_admission import PaperOrderSpec
from src.services.stock_radar_v2.observation_ledger import Observation



def test_offline_paper_simulation_runs_canonical_path_without_external_io(tmp_path):
    now = datetime.now(timezone.utc)
    capability = create_paper_adapter()
    evidence = Observation(
        observation_id="obs-sim-001",
        detector_status="CONFIRMED",
        evidence_ids=("snapshot-sim-001",),
        strategy_gate_results={"entry_gate": "PASS"},
        strategy_eligible=True,
        portfolio_admissible=True,
        portfolio_block_reasons=(),
        execution_feasible=True,
        decision_available_at=now.timestamp() - 2,
        confirmed_at=now.timestamp() - 1,
        earliest_executable_at=now.timestamp() - 1,
        canonical_permission="PASS",
    )
    spec = PaperOrderSpec(
        action_id="action-sim-001",
        symbol="AMD",
        side=Side.BUY,
        qty=Decimal("1"),
        limit_price=Decimal("100"),
        max_slippage=Decimal("0.001"),
        strategy_id="offline-simulation",
        evidence_snapshot_id="snapshot-sim-001",
        valid_until=now + timedelta(minutes=5),
    )
    guard = RiskGuard(
        RiskLimits(
            allowed_symbols=frozenset({"AMD"}),
            max_order_notional=1000,
            max_order_qty=10,
            max_symbol_exposure=1000,
            max_portfolio_exposure=1000,
            max_slippage=1,
            max_open_orders=10,
            data_ttl_seconds=60,
            account_ttl_seconds=60,
        )
    )

    report = run_offline_paper_simulation(
        capability,
        guard,
        evidence,
        spec,
        RiskContext(now=now, data_as_of=now, session="RTH"),
        root_path=tmp_path,
        runtime_generation="simulation-runtime-1",
        account_generation="simulation-account-1",
    )

    assert report.completed_without_external_io is True
    assert report.runtime.state.value == "READY"
    assert report.result.order_state.value == "ACCEPTED"
    assert report.result.broker_order_id == "paper-order-1"
    assert report.execution_store_path.endswith("execution.sqlite")
    assert report.shadow_store_path.endswith("shadow.sqlite")
    assert capability.adapter.calls == [("place", report.result.intent_id)]
