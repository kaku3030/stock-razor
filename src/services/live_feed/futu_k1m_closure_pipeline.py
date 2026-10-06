from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock

from data_provider.live_feed_types import ProviderEventKind
from data_provider.market_data_adapter import Bar

from .controller import AppliedDataEvidence
from .futu_k1m_forming_accumulator import FutuK1MFormingAccumulator
from .futu_research_bridge import closed_futu_minute_to_bar


@dataclass(frozen=True)
class FutuK1MClosurePipelineResult:
    status: str
    symbol: str | None = None
    closed_bar_queued: bool = False
    reason: str | None = None


class FutuK1MClosurePipeline:
    """Convert writer-applied Futu K_1M evidence into closed research bars.

    Raw provider callbacks and ingress-accepted events are intentionally not
    accepted by this boundary. Callers must supply AppliedDataEvidence drained
    from LiveFeedController after its single-writer relevance checks. The
    single consumer/main loop drains canonical bars later. Malformed,
    mismatched, or out-of-order evidence fails closed into bounded diagnostics.
    """

    def __init__(
        self,
        *,
        max_diagnostics: int = 100,
        max_pending_closed: int = 1024,
    ) -> None:
        if max_diagnostics <= 0:
            raise ValueError("max_diagnostics must be positive")
        if max_pending_closed <= 0:
            raise ValueError("max_pending_closed must be positive")
        self._accumulator = FutuK1MFormingAccumulator()
        self._max_pending_closed = max_pending_closed
        self._closed: deque[Bar] = deque()
        self._diagnostics: deque[dict[str, str]] = deque(maxlen=max_diagnostics)
        self._lock = Lock()
        self._event_count = 0
        self._closed_count = 0
        self._blocked_count = 0

    def consume_event(
        self, evidence: AppliedDataEvidence
    ) -> FutuK1MClosurePipelineResult:
        if not isinstance(evidence, AppliedDataEvidence):
            raise TypeError("writer-applied AppliedDataEvidence is required")
        event = evidence.event
        if event.event_kind is not ProviderEventKind.DATA:
            return FutuK1MClosurePipelineResult(
                status="IGNORED", reason="NON_DATA_EVENT"
            )
        key = event.semantic_stream_key
        if (
            event.provider_id != "futu"
            or key is None
            or key.provider_id != "futu"
            or key.market != "us"
            or key.stream_type != "K_1M"
            or key.timeframe != "1m"
        ):
            return FutuK1MClosurePipelineResult(
                status="IGNORED", reason="OUT_OF_SCOPE_STREAM"
            )

        symbol = key.symbol
        payload = event.payload
        if payload is None:
            return self._blocked(symbol, "MISSING_DATA_PAYLOAD")
        payload_symbol = str(payload.get("code") or "").strip()
        if payload_symbol != symbol:
            return self._blocked(symbol, "PAYLOAD_SYMBOL_MISMATCH")

        with self._lock:
            self._event_count += 1
            try:
                closed, _forming = self._accumulator.ingest(payload)
                if closed is None:
                    return FutuK1MClosurePipelineResult(
                        status="FORMING", symbol=symbol
                    )
                bar = closed_futu_minute_to_bar(
                    closed, received_at=event.observed_at_utc
                )
                if bar.symbol != symbol:
                    raise ValueError("canonical bar symbol mismatch")
                if len(self._closed) >= self._max_pending_closed:
                    self._blocked_count += 1
                    self._diagnostics.append(
                        {"symbol": symbol, "reason": "CLOSED_QUEUE_FULL"}
                    )
                    return FutuK1MClosurePipelineResult(
                        status="BLOCKED",
                        symbol=symbol,
                        reason="CLOSED_QUEUE_FULL",
                    )
                self._closed.append(bar)
                self._closed_count += 1
                return FutuK1MClosurePipelineResult(
                    status="CLOSED_QUEUED",
                    symbol=symbol,
                    closed_bar_queued=True,
                )
            except Exception as exc:
                self._blocked_count += 1
                reason = type(exc).__name__
                self._diagnostics.append({"symbol": symbol, "reason": reason})
                return FutuK1MClosurePipelineResult(
                    status="BLOCKED", symbol=symbol, reason=reason
                )

    def _blocked(
        self, symbol: str | None, reason: str
    ) -> FutuK1MClosurePipelineResult:
        with self._lock:
            self._blocked_count += 1
            self._diagnostics.append({"symbol": symbol or "", "reason": reason})
        return FutuK1MClosurePipelineResult(
            status="BLOCKED", symbol=symbol, reason=reason
        )

    def peek_closed(self) -> Bar | None:
        """Return the oldest closed bar without removing it."""
        with self._lock:
            return self._closed[0] if self._closed else None

    def ack_closed(self, expected: Bar) -> bool:
        """Remove the oldest closed bar only after downstream acceptance."""
        with self._lock:
            if not self._closed:
                return False
            if self._closed[0] != expected:
                raise ValueError("closed-bar acknowledgement does not match queue head")
            self._closed.popleft()
            return True

    def drain_closed(self) -> tuple[Bar, ...]:
        """Compatibility/test helper; runtime consumers should prefer peek/ack."""
        with self._lock:
            bars = tuple(self._closed)
            self._closed.clear()
            return bars

    def diagnostics(self) -> dict[str, object]:
        with self._lock:
            return {
                "event_count": self._event_count,
                "closed_count": self._closed_count,
                "blocked_count": self._blocked_count,
                "queued_closed_count": len(self._closed),
                "recent_errors": tuple(dict(item) for item in self._diagnostics),
            }
