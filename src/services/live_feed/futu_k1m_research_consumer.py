from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Protocol

from .controller import LiveFeedController
from .futu_k1m_closure_pipeline import FutuK1MClosurePipeline


class MinuteBarIngestor(Protocol):
    def ingest(self, bar) -> bool: ...


@dataclass(frozen=True)
class FutuK1MResearchConsumerResult:
    evidence_processed: int
    closure_blocked: int
    bars_ingested: int
    bars_unchanged: int
    stopped_reason: str | None = None


class FutuK1MResearchConsumer:
    """Single-consumer bridge from writer-applied DATA to canonical 1m cache.

    The consumer never reads raw provider callbacks. It drains at most one
    writer-applied evidence item at a time, then asks the closure pipeline to
    prove the prior minute closed. Closed bars use peek/ack: cache ingestion
    must succeed before the closure queue head is removed.
    """

    def __init__(
        self,
        controller: LiveFeedController,
        closure_pipeline: FutuK1MClosurePipeline,
        market_data: MinuteBarIngestor,
        *,
        max_diagnostics: int = 100,
    ) -> None:
        if max_diagnostics <= 0:
            raise ValueError("max_diagnostics must be positive")
        self._controller = controller
        self._closure = closure_pipeline
        self._market_data = market_data
        self._diagnostics: deque[dict[str, str]] = deque(maxlen=max_diagnostics)

    def run_once(self, *, max_events: int = 100) -> FutuK1MResearchConsumerResult:
        if max_events <= 0:
            raise ValueError("max_events must be positive")

        evidence_processed = 0
        closure_blocked = 0
        bars_ingested = 0
        bars_unchanged = 0

        flushed = self._flush_closed()
        if flushed[2] is not None:
            return FutuK1MResearchConsumerResult(
                evidence_processed=0,
                closure_blocked=0,
                bars_ingested=flushed[0],
                bars_unchanged=flushed[1],
                stopped_reason=flushed[2],
            )
        bars_ingested += flushed[0]
        bars_unchanged += flushed[1]

        while evidence_processed < max_events:
            batch = self._controller.drain_applied_data_for_consumer(max_items=1)
            if not batch:
                break
            evidence = batch[0]
            try:
                result = self._closure.consume_event(evidence)
            except Exception as exc:
                reason = f"CLOSURE_EXCEPTION:{type(exc).__name__}"
                self._diagnostics.append({"reason": reason})
                return FutuK1MResearchConsumerResult(
                    evidence_processed=evidence_processed + 1,
                    closure_blocked=closure_blocked,
                    bars_ingested=bars_ingested,
                    bars_unchanged=bars_unchanged,
                    stopped_reason=reason,
                )

            evidence_processed += 1
            if result.status == "BLOCKED":
                closure_blocked += 1

            flushed = self._flush_closed()
            bars_ingested += flushed[0]
            bars_unchanged += flushed[1]
            if flushed[2] is not None:
                return FutuK1MResearchConsumerResult(
                    evidence_processed=evidence_processed,
                    closure_blocked=closure_blocked,
                    bars_ingested=bars_ingested,
                    bars_unchanged=bars_unchanged,
                    stopped_reason=flushed[2],
                )

        return FutuK1MResearchConsumerResult(
            evidence_processed=evidence_processed,
            closure_blocked=closure_blocked,
            bars_ingested=bars_ingested,
            bars_unchanged=bars_unchanged,
        )

    def diagnostics(self) -> tuple[dict[str, str], ...]:
        return tuple(dict(item) for item in self._diagnostics)

    def _flush_closed(self) -> tuple[int, int, str | None]:
        ingested = 0
        unchanged = 0
        while True:
            bar = self._closure.peek_closed()
            if bar is None:
                return ingested, unchanged, None
            try:
                changed = self._market_data.ingest(bar)
            except Exception as exc:
                reason = f"CACHE_INGEST_EXCEPTION:{type(exc).__name__}"
                self._diagnostics.append(
                    {"reason": reason, "symbol": getattr(bar, "symbol", "")}
                )
                return ingested, unchanged, reason
            if not self._closure.ack_closed(bar):
                reason = "CLOSED_ACK_MISSING"
                self._diagnostics.append(
                    {"reason": reason, "symbol": getattr(bar, "symbol", "")}
                )
                return ingested, unchanged, reason
            if changed:
                ingested += 1
            else:
                unchanged += 1
