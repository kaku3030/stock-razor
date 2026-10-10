"""Controlled construction helpers for the offline paper runtime.

This module deliberately separates construction from activation.  Building a
runtime creates only the configured durable stores; it never starts a loop,
calls AWS, contacts a broker, or sends notifications.  Activation is explicit
and remains fail-closed behind PAPER_AUTO_READY.
"""

from __future__ import annotations

import os

from .execution_engine import (
    ExecutionBlocked,
    ExecutionEngine,
    _PaperCapability,
    ExecutionStore,
    RiskGuard,
)
from .paper_runtime_orchestrator import PaperRuntimeOrchestrator
from .paper_runtime_store_config import PaperRuntimeStoreConfig


def build_paper_runtime(
    capability: _PaperCapability,
    risk_guard: RiskGuard,
    *,
    runtime_generation: str,
    account_generation: str,
    config: PaperRuntimeStoreConfig | None = None,
    start: bool = False,
) -> PaperRuntimeOrchestrator:
    """Build an offline Paper Runtime without implicitly activating it.

    ``start=False`` is the only default.  Passing ``start=True`` is an explicit
    activation request and requires ``PAPER_AUTO_READY=YES``.  The helper still
    performs no scheduling and has no live/provider path; it only invokes the
    existing offline reconciliation during explicit start.
    """

    if start and os.getenv("PAPER_AUTO_READY", "NO").strip().upper() != "YES":
        raise ExecutionBlocked("PAPER_AUTO_READY is not enabled")

    store_config = config or PaperRuntimeStoreConfig.from_env()
    engine = ExecutionEngine(
        capability,
        risk_guard,
        ExecutionStore(store_config.execution_path),
    )
    runtime = PaperRuntimeOrchestrator.from_config(
        engine,
        runtime_generation=runtime_generation,
        account_generation=account_generation,
        config=store_config,
    )
    if start:
        runtime.start()
    return runtime
