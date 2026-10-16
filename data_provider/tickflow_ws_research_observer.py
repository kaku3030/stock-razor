"""Bounded TickFlow WebSocket quote evidence for the private research cache.

This adapter consumes the official SDK stream only when the research worker
explicitly enables it. It records sanitized protocol observations; it is not a
market-data owner and never qualifies continuity, latency, bar closure, or
Radar admission.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import time
from typing import Any, Iterable


_SYMBOL_RE = __import__("re").compile(r"^[0-9]{6}\.(?:SH|SZ)$")
_MAX_SYMBOLS = 200
_SUBSCRIBE_BATCH_SIZE = 5
_MAX_LAG_SAMPLES = 4096


def _symbols(values: Iterable[str]) -> tuple[str, ...]:
    result = tuple(str(value).upper() for value in values)
    if not result or len(result) > _MAX_SYMBOLS or len(set(result)) != len(result):
        raise ValueError("invalid TickFlow WebSocket symbols")
    if not all(_SYMBOL_RE.fullmatch(value) for value in result):
        raise ValueError("invalid TickFlow WebSocket symbols")
    return result


class TickFlowWebSocketResearchObserver:
    """Collect fixed, non-sensitive quote-stream counters."""

    def __init__(self, symbols: Iterable[str], *, now_ms: Any = None):
        self.symbols = frozenset(_symbols(symbols))
        self._now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)
        self.subscription_call = "NOT_VERIFIED"
        self.connection_call = "NOT_VERIFIED"
        self._latest: dict[str, int] = {}
        self._lags: list[int] = []
        self._counts = {
            "quote_callbacks": 0,
            "quote_events": 0,
            "initial_snapshot_candidates": 0,
            "post_initial_update_candidates": 0,
            "duplicate_timestamp_events": 0,
            "out_of_order_timestamp_events": 0,
            "unrequested_symbol_events": 0,
            "invalid_timestamp_events": 0,
            "error_callbacks": 0,
        }

    def subscribe(self, stream: Any) -> None:
        """Issue the documented SDK subscribe call; this is not server ACK."""
        symbols = sorted(self.symbols)
        # Keep each command at the previously verified five-symbol size while
        # using the documented append semantics to cover the phase-bounded
        # scan on one connection.
        for offset in range(0, len(symbols), _SUBSCRIBE_BATCH_SIZE):
            stream.subscribe("quotes", symbols[offset:offset + _SUBSCRIBE_BATCH_SIZE])
        self.subscription_call = "PASS"

    def mark_connected(self) -> None:
        self.connection_call = "PASS"

    def on_quotes(self, quotes: Any) -> None:
        self._counts["quote_callbacks"] += 1
        if not isinstance(quotes, (list, tuple)):
            return
        self._counts["quote_events"] += len(quotes)
        received_ms = self._now_ms()
        if type(received_ms) is not int or received_ms < 0:
            raise ValueError("invalid local receive clock")
        for quote in quotes:
            if not isinstance(quote, dict):
                self._counts["invalid_timestamp_events"] += 1
                continue
            symbol = quote.get("symbol")
            if symbol not in self.symbols:
                self._counts["unrequested_symbol_events"] += 1
                continue
            timestamp = quote.get("timestamp")
            if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                    or not math.isfinite(timestamp) or timestamp < 1_000_000_000_000
                    or timestamp >= 10_000_000_000_000):
                self._counts["invalid_timestamp_events"] += 1
                continue
            current = int(timestamp)
            previous = self._latest.get(symbol)
            if previous is None:
                self._counts["initial_snapshot_candidates"] += 1
                self._latest[symbol] = current
            elif current == previous:
                self._counts["duplicate_timestamp_events"] += 1
            elif current < previous:
                self._counts["out_of_order_timestamp_events"] += 1
            else:
                self._counts["post_initial_update_candidates"] += 1
                self._latest[symbol] = current
                if len(self._lags) < _MAX_LAG_SAMPLES:
                    self._lags.append(received_ms - current)

    def on_error(self, _message: Any = None) -> None:
        self._counts["error_callbacks"] += 1

    def summary(self, *, observed_at_utc: datetime | None = None) -> dict[str, Any]:
        observed = observed_at_utc or datetime.now(timezone.utc)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("observed_at_utc must be timezone-aware")
        lag_bucket = "NOT_VERIFIED"
        if self._lags and not any(value < 0 for value in self._lags):
            p95 = sorted(self._lags)[max(0, math.ceil(len(self._lags) * 0.95) - 1)]
            lag_bucket = (
                "UNDER_2S" if p95 <= 2_000 else
                "TWO_TO_FIVE_S" if p95 <= 5_000 else
                "FIVE_TO_THIRTY_S" if p95 <= 30_000 else "OVER_THIRTY_S"
            )
        return {
            "schema": "stock_razor_tickflow_ws_research_evidence_v0_1",
            "observed_at_utc": observed.astimezone(timezone.utc).isoformat(),
            "symbols": sorted(self.symbols),
            **self._counts,
            "post_initial_lag_samples": len(self._lags),
            "post_initial_lag_bucket": lag_bucket,
            "subscription_call": self.subscription_call,
            "subscription_ack": "NOT_OBSERVABLE_VIA_OFFICIAL_SYNC_SDK",
            "connection_call": self.connection_call,
            "snapshot_vs_live_evidence": "NOT_VERIFIED",
            "continuous_feed_qualified": False,
            "bar_finality": "NOT_VERIFIED",
            "radar_admission": "BLOCKED",
            "source_arbiter_admission": "BLOCKED",
            "live_trade": False,
        }


def attach_tickflow_stream(client: Any, symbols: Iterable[str]) -> TickFlowWebSocketResearchObserver:
    """Attach callbacks and start the official SDK stream in non-blocking mode."""
    observer = TickFlowWebSocketResearchObserver(symbols)
    stream = client.stream
    stream.on_quotes(observer.on_quotes)
    stream.on_error(observer.on_error)
    observer.subscribe(stream)
    stream.connect(block=False)
    observer.mark_connected()
    return observer
