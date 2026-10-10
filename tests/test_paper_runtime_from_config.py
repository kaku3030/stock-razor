from decimal import Decimal

import pytest

from src.services.execution_engine import (
    ExecutionBlocked,
    ExecutionEngine,
    ExecutionStore,
    RiskGuard,
    RiskLimits,
    create_paper_adapter,
)
from src.services.paper_runtime_orchestrator import (
    PaperRuntimeOrchestrator,
    PaperRuntimeState,
)
from src.services.paper_runtime_store_config import PaperRuntimeStoreConfig


def _risk_guard():
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


def test_from_config_requires_matching_execution_store_and_builds_shadow_store(tmp_path):
    execution_path = tmp_path / "runtime.sqlite"
    shadow_path = tmp_path / "shadow.sqlite"
    capability = create_paper_adapter()
    engine = ExecutionEngine(capability, _risk_guard(), ExecutionStore(execution_path))
    config = PaperRuntimeStoreConfig(execution_path, shadow_path)

    owner = PaperRuntimeOrchestrator.from_config(
        engine,
        runtime_generation="runtime-1",
        account_generation="account-1",
        config=config,
    )

    assert owner.state is PaperRuntimeState.NEW
    owner.start()
    assert owner.state is PaperRuntimeState.READY
    owner.stop()


def test_from_config_fails_closed_on_execution_store_mismatch(tmp_path):
    capability = create_paper_adapter()
    engine = ExecutionEngine(
        capability,
        _risk_guard(),
        ExecutionStore(tmp_path / "actual.sqlite"),
    )
    config = PaperRuntimeStoreConfig(
        tmp_path / "configured.sqlite",
        tmp_path / "shadow.sqlite",
    )

    with pytest.raises(ExecutionBlocked, match="does not match"):
        PaperRuntimeOrchestrator.from_config(
            engine,
            runtime_generation="runtime-1",
            account_generation="account-1",
            config=config,
        )


def test_from_config_reads_environment_without_creating_store_files(tmp_path, monkeypatch):
    execution_path = tmp_path / "runtime.sqlite"
    shadow_path = tmp_path / "shadow.sqlite"
    monkeypatch.setenv("PAPER_EXECUTION_STORE_PATH", str(execution_path))
    monkeypatch.setenv("PAPER_SHADOW_STORE_PATH", str(shadow_path))

    capability = create_paper_adapter()
    engine = ExecutionEngine(capability, _risk_guard(), ExecutionStore(execution_path))
    owner = PaperRuntimeOrchestrator.from_config(
        engine,
        runtime_generation="runtime-1",
        account_generation="account-1",
    )

    assert owner.state is PaperRuntimeState.NEW
    assert not shadow_path.exists()
