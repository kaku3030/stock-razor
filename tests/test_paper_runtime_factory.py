from __future__ import annotations

from pathlib import Path

import pytest

from src.services.execution_engine import (
    ExecutionBlocked,
    RiskGuard,
    RiskLimits,
    create_paper_adapter,
)
from src.services.paper_runtime_factory import build_paper_runtime
from src.services.paper_runtime_orchestrator import PaperRuntimeState
from src.services.paper_runtime_store_config import PaperRuntimeStoreConfig


def _config(tmp_path: Path) -> PaperRuntimeStoreConfig:
    return PaperRuntimeStoreConfig(
        tmp_path / "execution.sqlite",
        tmp_path / "shadow.sqlite",
    )


def _risk_guard() -> RiskGuard:
    return RiskGuard(
        RiskLimits(
            allowed_symbols=frozenset({"TEST"}),
            max_order_notional=100000,
            max_order_qty=1000,
            max_symbol_exposure=100000,
            max_portfolio_exposure=100000,
            max_slippage=1,
            max_open_orders=10,
            data_ttl_seconds=300,
            account_ttl_seconds=300,
        )
    )


def test_build_is_explicit_and_does_not_start_or_schedule(tmp_path: Path) -> None:
    capability = create_paper_adapter()

    runtime = build_paper_runtime(
        capability,
        _risk_guard(),
        runtime_generation="runtime-1",
        account_generation="account-1",
        config=_config(tmp_path),
    )

    assert runtime.state is PaperRuntimeState.NEW
    assert capability.adapter.calls == []
    assert (tmp_path / "execution.sqlite").exists()
    assert (tmp_path / "shadow.sqlite").exists()


def test_explicit_start_is_blocked_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAPER_AUTO_READY", raising=False)

    with pytest.raises(ExecutionBlocked, match="PAPER_AUTO_READY"):
        build_paper_runtime(
            create_paper_adapter(),
            _risk_guard(),
            runtime_generation="runtime-1",
            account_generation="account-1",
            config=_config(tmp_path),
            start=True,
        )


def test_explicit_start_requires_opt_in_and_reconciles_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_AUTO_READY", "YES")
    capability = create_paper_adapter()

    runtime = build_paper_runtime(
        capability,
        _risk_guard(),
        runtime_generation="runtime-1",
        account_generation="account-1",
        config=_config(tmp_path),
        start=True,
    )

    assert runtime.state is PaperRuntimeState.READY
    assert capability.adapter.calls == []