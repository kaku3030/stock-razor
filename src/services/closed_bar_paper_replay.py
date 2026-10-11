"""Historical closed-bar fill simulator — deterministic research, NOT broker Paper.

Research signals and 60m trend decisions are upstream inputs. No strategy or
portfolio authorization is inferred here. All observed 15m bars (including
future outcome bars) are caller-supplied historical evidence. Signal checks
use only the selected CLOSED 15m bar and an explicitly prior 60m gate.
No provider, broker, network, token, scheduler or notification IO.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal


def _d(value: object, name: str, *, zero_allowed: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be finite decimal")
    try:
        x = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite decimal") from exc
    if not x.is_finite() or (x < 0 if zero_allowed else x <= 0):
        raise ValueError(f"{name} must be positive finite decimal")
    return x


def _t(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Closed15mBar:
    start: datetime
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source: str
    closed: bool = True

    def __post_init__(self) -> None:
        start, end = _t(self.start, "start"), _t(self.end, "end")
        if end - start != timedelta(minutes=15):
            raise ValueError("BAR_DURATION_NOT_15M")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, _d(getattr(self, name), name))
        object.__setattr__(self, "volume", _d(self.volume, "volume", zero_allowed=True))
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.high < self.low:
            raise ValueError("BAR_OHLC_INVALID")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("BAR_SOURCE_MISSING")


@dataclass(frozen=True)
class UpstreamHourlyGate:
    """As-of truth from an independently checked, CLOSED 60m input."""

    closed_bar_end: datetime
    passed: bool
    bar_was_closed: bool
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "closed_bar_end", _t(self.closed_bar_end, "hourly_end"))
        if not isinstance(self.passed, bool) or not isinstance(self.bar_was_closed, bool):
            raise ValueError("HOURLY_GATE_FLAGS_INVALID")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("HOURLY_SOURCE_MISSING")


@dataclass(frozen=True)
class HistoricalEntryBand:
    low: Decimal
    high: Decimal
    stop: Decimal
    target: Decimal
    entry_slippage_per_share: Decimal = Decimal("0")
    exit_slippage_per_share: Decimal = Decimal("0")
    round_trip_fee_per_share: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for name in ("low", "high", "stop", "target"):
            object.__setattr__(self, name, _d(getattr(self, name), name))
        for name in ("entry_slippage_per_share", "exit_slippage_per_share", "round_trip_fee_per_share"):
            object.__setattr__(self, name, _d(getattr(self, name), name, zero_allowed=True))
        if self.low > self.high or self.stop >= self.low or self.target <= self.high:
            raise ValueError("ENTRY_BAND_STOP_TARGET_INVALID")


@dataclass(frozen=True)
class ClosedBarResearchReceipt:
    status: str
    reason: str
    decision_as_of: datetime | None = None
    hypothetical_entry_at: datetime | None = None
    entry: Decimal | None = None
    exit: Decimal | None = None
    risk_per_share: Decimal | None = None
    net_r: Decimal | None = None
    exit_reason: str | None = None
    research_only: Literal[True] = True
    future_bars_are_outcome_only: Literal[True] = True
    broker_paper_order_submitted: Literal[False] = False
    external_simulator_verified: Literal[False] = False
    paper_auto_ready: Literal[False] = False
    radar_admission: Literal["BLOCKED"] = "BLOCKED"
    live_trade: Literal[False] = False


def replay_closed_bar_long(
    bars: tuple[Closed15mBar, ...],
    *,
    decision_index: int,
    hourly: UpstreamHourlyGate,
    entry: HistoricalEntryBand,
) -> ClosedBarResearchReceipt:
    """One supplied upstream long signal, next closed-bar open; stop-first.

    Does not calculate a signal from future data. Next bar open is a
    *hypothetical* fill, NOT actual order execution or liquidity proof.
    """
    if not isinstance(bars, tuple) or len(bars) > 128 or not bars:
        return ClosedBarResearchReceipt("BLOCKED", "BAR_SERIES_INVALID")
    if any(not isinstance(b, Closed15mBar) for b in bars):
        return ClosedBarResearchReceipt("BLOCKED", "BAR_TYPE_INVALID")
    if any(not b.closed for b in bars):
        return ClosedBarResearchReceipt("BLOCKED", "UNCLOSED_15M_BAR")
    if any(b.start != bars[0].start + timedelta(minutes=15 * i) for i, b in enumerate(bars)):
        return ClosedBarResearchReceipt("BLOCKED", "BAR_GAP_OR_DUPLICATE")
    if any(b.source != bars[0].source for b in bars):
        return ClosedBarResearchReceipt("BLOCKED", "MIXED_PROVIDER")
    if not isinstance(decision_index, int) or isinstance(decision_index, bool) or decision_index < 0 or decision_index >= len(bars):
        return ClosedBarResearchReceipt("BLOCKED", "DECISION_INDEX_INVALID")
    decision_time = bars[decision_index].end
    if not isinstance(hourly, UpstreamHourlyGate) or not isinstance(entry, HistoricalEntryBand):
        return ClosedBarResearchReceipt("BLOCKED", "UPSTREAM_GATE_OR_PLAN_MISSING", decision_time)
    if (not hourly.passed or not hourly.bar_was_closed or hourly.source != bars[0].source
        or hourly.closed_bar_end > decision_time
        or decision_time - hourly.closed_bar_end > timedelta(minutes=60)):
        return ClosedBarResearchReceipt("BLOCKED", "60M_GATE_NOT_PIT_QUALIFIED", decision_time)
    if decision_index + 1 >= len(bars):
        return ClosedBarResearchReceipt("BLOCKED", "NEXT_15M_OPEN_UNAVAILABLE", decision_time)
    next_bar = bars[decision_index + 1]
    # The input is exactly one contiguous session; never infer overnight fill.
    if next_bar.start.date() != decision_time.date():
        return ClosedBarResearchReceipt("BLOCKED", "NEW_SESSION_ORDER_NOT_ALLOWED", decision_time)

    entry_fill = next_bar.open + entry.entry_slippage_per_share
    if entry_fill < entry.low or entry_fill > entry.high:
        return ClosedBarResearchReceipt("NO_FILL", "NEXT_OPEN_OUTSIDE_ENTRY_BAND", decision_time)
    if entry_fill <= entry.stop or entry_fill >= entry.target:
        return ClosedBarResearchReceipt("NO_FILL", "NEXT_OPEN_ALREADY_INVALIDATED", decision_time)
    risk = entry_fill - entry.stop
    exit_fill: Decimal | None = None
    reason = "EOD_CLOSE"
    for candle in bars[decision_index + 1:]:
        # A stop gap fills at the worse opening, not the theoretical stop.
        if candle.open <= entry.stop:
            exit_fill = candle.open - entry.exit_slippage_per_share
            reason = "STOP_GAP_OPEN"
            break
        if candle.low <= entry.stop:
            exit_fill = entry.stop - entry.exit_slippage_per_share
            # Both hit: stop first. Bar ordering is unknown.
            reason = "STOP_FIRST_AMBIGUOUS" if candle.high >= entry.target else "STOP"
            break
        if candle.high >= entry.target:
            exit_fill = entry.target - entry.exit_slippage_per_share
            reason = "TARGET"
            break
    if exit_fill is None:
        exit_fill = bars[-1].close - entry.exit_slippage_per_share
    pnl = exit_fill - entry_fill - entry.round_trip_fee_per_share
    return ClosedBarResearchReceipt(
        status="HYPOTHETICAL_CLOSED_BAR_RESULT",
        reason="OFFLINE_ONLY_NOT_BROKER_FILL",
        decision_as_of=decision_time,
        hypothetical_entry_at=next_bar.start,
        entry=entry_fill,
        exit=exit_fill,
        risk_per_share=risk,
        net_r=pnl / risk,
        exit_reason=reason,
    )
