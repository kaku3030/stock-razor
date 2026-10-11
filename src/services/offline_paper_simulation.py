"""Explicit, offline Paper Simulation runner.

The runner reuses the canonical Paper Runtime path for one deterministic
scenario.  It has no network, provider, broker, notification, scheduler, or
live-trading surface.  The caller must provide the upstream permission, order
specification, and risk context explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .execution_engine import (
    ExecutionEngine,
    ExecutionStore,
    OrderState,
    RiskContext,
    RiskGuard,
    _PaperCapability,
)
from .paper_execution_admission import ExecutionAdmissionEvidence, PaperOrderSpec
from .paper_runtime_factory import build_paper_runtime
from .paper_runtime_orchestrator import PaperRuntimeResult, PaperRuntimeSnapshot
from .paper_runtime_store_config import PaperRuntimeStoreConfig


@dataclass(frozen=True)
class OfflinePaperSimulationReport:
    runtime: PaperRuntimeSnapshot
    result: PaperRuntimeResult
    execution_store_path: str
    shadow_store_path: str

    @property
    def completed_without_external_io(self) -> bool:
        return self.result.order_state in {
            OrderState.ACCEPTED,
            OrderState.PARTIAL,
            OrderState.FILLED,
            OrderState.REJECTED,
        }


def run_offline_paper_simulation(
    capability: _PaperCapability,
    risk_guard: RiskGuard,
    evidence: ExecutionAdmissionEvidence,
    spec: PaperOrderSpec,
    context: RiskContext,
    *,
    root_path: str | Path,
    runtime_generation: str,
    account_generation: str,
) -> OfflinePaperSimulationReport:
    """Run one explicit offline scenario through the canonical Paper path."""

    root = Path(root_path)
    config = PaperRuntimeStoreConfig(
        execution_path=root / "execution.sqlite",
        shadow_path=root / "shadow.sqlite",
    )
    runtime = build_paper_runtime(
        capability,
        risk_guard,
        runtime_generation=runtime_generation,
        account_generation=account_generation,
        config=config,
    )
    runtime.start()
    result = runtime.process(evidence, spec, context)
    return OfflinePaperSimulationReport(
        runtime=runtime.snapshot(),
        result=result,
        execution_store_path=str(config.execution_path),
        shadow_store_path=str(config.shadow_path),
    )