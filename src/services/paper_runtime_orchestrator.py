"""Single-writer, paper-only runtime coordinator.

The coordinator owns lifecycle ordering only:

permission evidence -> paper admission -> shadow preview -> existing RiskGuard /
ExecutionEngine -> factory-issued paper adapter.

It never creates a live adapter, never owns strategy decisions, and never
changes broker/account truth semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
import threading

from .execution_engine import ExecutionBlocked, ExecutionEngine, ExecutionStore, OrderState, RiskContext
from .live_shadow import ShadowExecutionCapability
from .paper_runtime_store_config import PaperRuntimeStoreConfig
from .paper_execution_admission import (
    ExecutionAdmissionEvidence,
    PaperOrderSpec,
    build_paper_order_intent,
    build_paper_order_intent_from_trade_plan,
)
from .trade_plan import TradePlan
from .trade_lifecycle import (
    TradeLifecycleSnapshot,
    project_trade_lifecycle,
)


class PaperRuntimeState(StrEnum):
    NEW = "NEW"
    READY = "READY"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class PaperRuntimeResult:
    runtime_generation: str
    intent_id: str
    shadow_decision_id: str
    order_state: OrderState
    broker_order_id: str | None
    fill_ids: tuple[str, ...]
    filled_qty: Decimal


@dataclass(frozen=True)
class PaperRuntimeSnapshot:
    runtime_generation: str
    account_generation: str
    state: PaperRuntimeState
    reconciliation_as_of: object | None
    journal_events: int
    order_records: int


class PaperRuntimeOrchestrator:
    """Serialize one paper execution owner behind an explicit lifecycle barrier."""

    __slots__ = (
        "_engine",
        "_shadow",
        "_runtime_generation",
        "_account_generation",
        "_lock",
        "_state",
        "_owner_thread_id",
    )

    @classmethod
    def from_config(
        cls,
        engine: ExecutionEngine,
        *,
        runtime_generation: str,
        account_generation: str,
        config: PaperRuntimeStoreConfig | None = None,
    ) -> "PaperRuntimeOrchestrator":
        """Build a runtime only when configured stores are durable and distinct."""

        store_config = config or PaperRuntimeStoreConfig.from_env()
        if engine.store.path != str(store_config.execution_path):
            raise ExecutionBlocked("execution store path does not match configuration")
        return cls(
            engine,
            runtime_generation=runtime_generation,
            account_generation=account_generation,
            shadow_store=ExecutionStore(store_config.shadow_path),
        )

    def __init__(
        self,
        engine: ExecutionEngine,
        *,
        runtime_generation: str,
        account_generation: str,
        shadow_store: ExecutionStore | None = None,
    ) -> None:
        if not runtime_generation.strip():
            raise ValueError("runtime_generation is required")
        if not account_generation.strip():
            raise ValueError("account_generation is required")
        if shadow_store is None or not shadow_store.durable:
            raise ExecutionBlocked("durable shadow store is required")
        if shadow_store is engine.store:
            raise ExecutionBlocked("shadow store must be separate from execution store")
        self._engine = engine
        self._shadow = ShadowExecutionCapability(engine.risk_guard, shadow_store)
        self._runtime_generation = runtime_generation
        self._account_generation = account_generation
        self._lock = threading.RLock()
        self._state = PaperRuntimeState.NEW
        self._owner_thread_id: int | None = None

    @property
    def state(self) -> PaperRuntimeState:
        return self._state

    def start(self) -> PaperRuntimeSnapshot:
        """Reconcile before accepting any permission or order intent."""

        with self._lock:
            if self._state is not PaperRuntimeState.NEW:
                raise ExecutionBlocked("paper runtime can only start from NEW")
            try:
                self._engine.reconcile()
            except Exception:
                self._state = PaperRuntimeState.FAILED
                raise
            self._owner_thread_id = threading.get_ident()
            self._state = PaperRuntimeState.READY
            return self.snapshot()

    def refresh_reconciliation(self, *, account_generation: str) -> PaperRuntimeSnapshot:
        """Refresh paper account truth on the single-writer owner thread."""

        with self._lock:
            if self._state is not PaperRuntimeState.READY:
                raise ExecutionBlocked("paper runtime is not READY")
            if threading.get_ident() != self._owner_thread_id:
                raise ExecutionBlocked("paper runtime requires the single-writer owner thread")
            if not account_generation.strip():
                raise ExecutionBlocked("account_generation is required")
            try:
                self._engine.reconcile()
            except Exception:
                self._state = PaperRuntimeState.FAILED
                raise
            self._account_generation = account_generation
            return self.snapshot()

    def process(
        self,
        evidence: ExecutionAdmissionEvidence,
        spec: PaperOrderSpec,
        context: RiskContext,
    ) -> PaperRuntimeResult:
        """Admit and execute exactly one paper action under the single writer lock."""

        with self._lock:
            if self._state is not PaperRuntimeState.READY:
                raise ExecutionBlocked("paper runtime is not READY")
            if threading.get_ident() != self._owner_thread_id:
                raise ExecutionBlocked("paper runtime requires the single-writer owner thread")
            try:
                intent = build_paper_order_intent(evidence, spec, now=context.now)
                reconciliation = self._engine.reconciliation
                if reconciliation is None:
                    raise ExecutionBlocked("startup reconciliation is required")
                preview = self._shadow.preview(
                    intent,
                    context,
                    reconciliation,
                    self._account_generation,
                )
                if not preview.eligible_for_execution:
                    raise ExecutionBlocked(
                        preview.reason or "shadow preview is not eligible for execution"
                    )
                record = self._engine.submit(intent, context)
            except ExecutionBlocked:
                raise
            except Exception:
                self._state = PaperRuntimeState.FAILED
                raise
            return PaperRuntimeResult(
                runtime_generation=self._runtime_generation,
                intent_id=intent.intent_id,
                shadow_decision_id=preview.decision_id,
                order_state=record.state,
                broker_order_id=record.broker_order_id,
                fill_ids=tuple(record.fill_ids),
                filled_qty=record.filled_qty,
            )

    def process_trade_plan(
        self,
        evidence: ExecutionAdmissionEvidence,
        plan: TradePlan,
        *,
        entry_price: Decimal,
        max_slippage: Decimal,
        evidence_snapshot_id: str,
        context: RiskContext,
    ) -> PaperRuntimeResult:
        """Translate one precomputed TradePlan and execute through the same paper path."""

        with self._lock:
            if self._state is not PaperRuntimeState.READY:
                raise ExecutionBlocked("paper runtime is not READY")
            if threading.get_ident() != self._owner_thread_id:
                raise ExecutionBlocked("paper runtime requires the single-writer owner thread")
            try:
                intent = build_paper_order_intent_from_trade_plan(
                    evidence,
                    plan,
                    entry_price=entry_price,
                    max_slippage=max_slippage,
                    evidence_snapshot_id=evidence_snapshot_id,
                    now=context.now,
                )
                reconciliation = self._engine.reconciliation
                if reconciliation is None:
                    raise ExecutionBlocked("startup reconciliation is required")
                preview = self._shadow.preview(
                    intent,
                    context,
                    reconciliation,
                    self._account_generation,
                )
                if not preview.eligible_for_execution:
                    raise ExecutionBlocked(
                        preview.reason or "shadow preview is not eligible for execution"
                    )
                record = self._engine.submit(intent, context)
            except ExecutionBlocked:
                raise
            except Exception:
                self._state = PaperRuntimeState.FAILED
                raise
            return PaperRuntimeResult(
                runtime_generation=self._runtime_generation,
                intent_id=intent.intent_id,
                shadow_decision_id=preview.decision_id,
                order_state=record.state,
                broker_order_id=record.broker_order_id,
                fill_ids=tuple(record.fill_ids),
                filled_qty=record.filled_qty,
            )

    def cancel(self, intent_id: str, *, at) -> PaperRuntimeResult:
        """Cancel one admitted paper order through the existing Execution Engine."""

        with self._lock:
            if self._state is not PaperRuntimeState.READY:
                raise ExecutionBlocked("paper runtime is not READY")
            if threading.get_ident() != self._owner_thread_id:
                raise ExecutionBlocked("paper runtime requires the single-writer owner thread")
            try:
                record = self._engine.cancel(intent_id, at)
            except ExecutionBlocked:
                raise
            except Exception:
                self._state = PaperRuntimeState.FAILED
                raise
            return PaperRuntimeResult(
                runtime_generation=self._runtime_generation,
                intent_id=record.intent.intent_id,
                shadow_decision_id="",
                order_state=record.state,
                broker_order_id=record.broker_order_id,
                fill_ids=tuple(record.fill_ids),
                filled_qty=record.filled_qty,
            )

    def replace(
        self,
        intent_id: str,
        evidence: ExecutionAdmissionEvidence,
        spec: PaperOrderSpec,
        context: RiskContext,
    ) -> PaperRuntimeResult:
        """Admit and replace one paper order without bypassing shadow/risk checks."""

        with self._lock:
            if self._state is not PaperRuntimeState.READY:
                raise ExecutionBlocked("paper runtime is not READY")
            if threading.get_ident() != self._owner_thread_id:
                raise ExecutionBlocked("paper runtime requires the single-writer owner thread")
            try:
                replacement = build_paper_order_intent(evidence, spec, now=context.now)
                reconciliation = self._engine.reconciliation
                if reconciliation is None:
                    raise ExecutionBlocked("startup reconciliation is required")
                preview = self._shadow.preview(
                    replacement,
                    context,
                    reconciliation,
                    self._account_generation,
                )
                if not preview.eligible_for_execution:
                    raise ExecutionBlocked(
                        preview.reason or "shadow preview is not eligible for execution"
                    )
                record = self._engine.replace(intent_id, replacement, context)
            except ExecutionBlocked:
                raise
            except Exception:
                self._state = PaperRuntimeState.FAILED
                raise
            return PaperRuntimeResult(
                runtime_generation=self._runtime_generation,
                intent_id=replacement.intent_id,
                shadow_decision_id=preview.decision_id,
                order_state=record.state,
                broker_order_id=record.broker_order_id,
                fill_ids=tuple(record.fill_ids),
                filled_qty=record.filled_qty,
            )

    def stop(self) -> PaperRuntimeSnapshot:
        """Stop the coordinator without inventing broker-side shutdown semantics."""

        with self._lock:
            if self._state is PaperRuntimeState.STOPPED:
                return self.snapshot()
            self._state = PaperRuntimeState.STOPPED
            return self.snapshot()

    def project_lifecycle(
        self,
        plan: TradePlan,
        *,
        now,
        trigger_ready: bool = False,
        execution_evidence_ready: bool = False,
        position=None,
        position_id: str | None = None,
    ) -> TradeLifecycleSnapshot:
        """Return the read-only lifecycle projection owned by this runtime."""
        return project_trade_lifecycle(
            plan,
            now=now,
            trigger_ready=trigger_ready,
            execution_evidence_ready=execution_evidence_ready,
            position=position,
            position_id=position_id,
        )

    def snapshot(self) -> PaperRuntimeSnapshot:
        with self._lock:
            reconciliation = self._engine.reconciliation
            return PaperRuntimeSnapshot(
                runtime_generation=self._runtime_generation,
                account_generation=self._account_generation,
                state=self._state,
                reconciliation_as_of=(
                    reconciliation.as_of if reconciliation is not None else None
                ),
                journal_events=len(self._engine.journal),
                order_records=len(self._engine.records),
            )
