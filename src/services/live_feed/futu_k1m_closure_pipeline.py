from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock

from data_provider.live_feed_types import ProviderEvent, ProviderEventKind
from data_provider.market_data_adapter import Bar

from .futu_k1m_forming_accumulator import FutuK1MFormingAccumulator
from .futu_research_bridge import closed_futu_minute_to_bar


@dataclass(frozen=True)
class FutuK1MClosurePipelineResult:
    status: str
    symbol: str | None = None
    closed_bar_queued: bool = False
    reason: str | None = None


class FutuK1MClosurePipeline:
    """Convert accepted Futu K_1M DATA evidence into queued closed 1m bars.

    Provider callbacks may call consume_event without writing the market-data
    cache. The single consumer/main loop drains canonical bars later.
    Malformed, mismatched, or out-of-order evidence fails closed into bounded
    diagnostics instead of escaping through the provider callback.
    """

    def __init__(self, *, max_diagnostics: int = 100) -> None:
        if max_diagnostics <= 0:
            raise ValueError("max_diagnostics must be positive")
        self._accumulator = FutuK1MFormingAccumulator()
        self._closed: deque[Bar] = deque()
        self._diagnostics: deque[dict[str, str]] = deque(maxlen=max_diagnostics)
        self._lock = Lock()
        self._event_count = 0
        self._closed_count = 0
        self._blocked_count = 0

    def consume_event(self, event: ProviderEvent) -> FutuK1MClosurePipelineResult:
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

    def drain_closed(self) -> tuple[Bar, ...]:
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
