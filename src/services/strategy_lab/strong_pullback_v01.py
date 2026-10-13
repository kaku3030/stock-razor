"""Strong Pullback Strategy V0.1, research-only and long-only.

This module is deliberately provider-agnostic.  It accepts only closed bars and
an explicit provenance certificate; it never fetches data or emits orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from statistics import median
from typing import Iterable, Sequence


class InstrumentKind(str, Enum):
    CN_ETF = "CN_ETF"
    US_TRADEABLE = "US_TRADEABLE"


class Pattern(str, Enum):
    A_FIRST_OR_SECOND_PULLBACK = "A"
    B_BREAKOUT_ACCEPTANCE = "B"
    C_CONTRACTION_BREAKOUT = "C"


@dataclass(frozen=True)
class Bar:
    end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool = True

    def __post_init__(self) -> None:
        values = (self.open, self.high, self.low, self.close, self.volume)
        if self.end.tzinfo is None or any(not isfinite(value) for value in values):
            raise ValueError("bar requires an aware timestamp and finite OHLCV")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("bar OHLC is inconsistent")
        if self.volume < 0:
            raise ValueError("bar volume must be non-negative")
        if not self.closed:
            raise ValueError("forming bars are not accepted by the strategy")


@dataclass(frozen=True)
class Provenance:
    instrument: InstrumentKind
    provider: str
    feed: str
    timezone: str
    pit_verified: bool
    survivorship_controlled: bool
    source_lineage: str


@dataclass(frozen=True)
class Qualification:
    status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Signal:
    pattern: Pattern
    index: int
    signal_end: datetime
    entry_reference: float
    support_or_breakout: float
    invalidation: float
    pullback_number: int | None
    rationale: tuple[str, ...]


@dataclass(frozen=True)
class Trade:
    pattern: Pattern
    entry_index: int
    exit_index: int
    entry: float
    exit: float
    risk: float
    net_return: float
    r_multiple: float
    outcome: str


@dataclass(frozen=True)
class BacktestReport:
    status: str
    trades: tuple[Trade, ...]
    expected_value: float | None
    win_rate: float | None
    average_win_r: float | None
    average_loss_r: float | None
    max_drawdown: float | None
    r_distribution: tuple[float, ...]
    scenario_stability: str
    reason: str | None = None


def qualify_data(provenance: Provenance, bars: Sequence[Bar]) -> Qualification:
    reasons: list[str] = []
    expected_provider = "tickflow" if provenance.instrument is InstrumentKind.CN_ETF else "alpaca"
    if provenance.provider.lower() != expected_provider:
        reasons.append("provider_not_qualified_for_instrument")
    if not provenance.feed.strip():
        reasons.append("feed_missing")
    if not provenance.timezone.strip():
        reasons.append("timezone_missing")
    if not provenance.source_lineage.strip():
        reasons.append("source_lineage_missing")
    if not provenance.pit_verified:
        reasons.append("pit_not_verified")
    if not provenance.survivorship_controlled:
        reasons.append("survivorship_control_not_verified")
    if not bars:
        reasons.append("bars_missing")
    return Qualification("PASS" if not reasons else "BLOCKED", tuple(reasons))


def _mean_volume(bars: Sequence[Bar]) -> float:
    return median(bar.volume for bar in bars)


def _trend_ok(daily: Sequence[Bar], hourly: Sequence[Bar]) -> bool:
    return (
        len(daily) >= 20
        and len(hourly) >= 20
        and daily[-1].close > median(bar.close for bar in daily[-20:])
        and hourly[-1].close > hourly[-4].close
    )


def detect_signals(
    *,
    daily: Sequence[Bar],
    hourly: Sequence[Bar],
    fifteen_minute: Sequence[Bar],
    provenance: Provenance,
) -> tuple[Signal, ...]:
    """Detect only signals whose trigger bar is closed and PIT-qualified.

    15m is the trigger timeframe.  5m is intentionally not used in V0.1;
    callers may use it only for a future execution-sensitivity study.
    """
    qualification = qualify_data(provenance, (*daily, *hourly, *fifteen_minute))
    if qualification.status != "PASS" or not _trend_ok(daily, hourly):
        return ()
    signals: list[Signal] = []
    for i in range(20, len(fifteen_minute)):
        bars = fifteen_minute[: i + 1]
        current = bars[-1]
        prior = bars[-21:-1]
        # Exclude the candidate setup window from the baseline; otherwise a
        # quiet pullback would lower its own comparison threshold.
        baseline_volume = _mean_volume(prior[-10:-3])
        recent = bars[-6:-1]
        if len(recent) < 5:
            continue
        support = min(bar.low for bar in prior[-10:])
        base = bars[-6:-1]
        base_high = max(bar.high for bar in base)
        base_low = min(bar.low for bar in base)
        range_now = base_high - base_low
        ranges = [bar.high - bar.low for bar in prior[-10:]]
        contraction = (
            range_now <= median(ranges) * 0.8
            and _mean_volume(base) <= baseline_volume * 0.7
            and current.close > base_high
            and current.volume >= baseline_volume * 1.2
        )
        if contraction:
            signals.append(
                Signal(
                    Pattern.C_CONTRACTION_BREAKOUT,
                    i,
                    current.end,
                    current.close,
                    base_high,
                    base_low,
                    None,
                    ("range_contraction", "volume_contraction", "closed_breakout"),
                )
            )
            continue
        pullback = bars[-4:-1]
        if len(pullback) == 3 and min(bar.low for bar in pullback) >= support * 0.985:
            quiet = _mean_volume(pullback) <= baseline_volume * 0.8
            reclaim = current.close > pullback[-1].high and current.volume >= baseline_volume
            if quiet and reclaim:
                prior_pullbacks = sum(1 for signal in signals if signal.pattern is Pattern.A_FIRST_OR_SECOND_PULLBACK)
                number = 1 if prior_pullbacks == 0 else 2
                signals.append(
                    Signal(
                        Pattern.A_FIRST_OR_SECOND_PULLBACK,
                        i,
                        current.end,
                        current.close,
                        support,
                        support * 0.985,
                        number,
                        ("daily_and_60m_trend", "3_bar_shallow_low", "volume_contraction", "closed_reclaim"),
                    )
                )
                continue
        breakout = max(bar.high for bar in prior)
        accepted = any(bar.low >= breakout * 0.99 and bar.close >= breakout * 0.995 for bar in bars[-4:-1])
        if current.close > breakout and current.volume >= baseline_volume * 1.5 and accepted:
            signals.append(
                Signal(
                    Pattern.B_BREAKOUT_ACCEPTANCE,
                    i,
                    current.end,
                    current.close,
                    breakout,
                    breakout * 0.99,
                    None,
                    ("prior_high_break", "volume_expansion", "accepted_retest", "closed_relaunch"),
                )
            )
            continue
    return tuple(signals)


def run_backtest(
    bars: Sequence[Bar],
    signals: Iterable[Signal],
    *,
    commission_bps: float = 5.0,
    slippage_bps: float = 5.0,
    horizon_bars: int = 12,
) -> BacktestReport:
    """Execute at next-bar open, stop first, then horizon close; no intrabar hindsight."""
    if not bars or commission_bps < 0 or slippage_bps < 0 or horizon_bars < 1:
        return BacktestReport("BLOCKED", (), None, None, None, None, (), "UNKNOWN", "invalid_backtest_inputs")
    trades: list[Trade] = []
    for signal in signals:
        entry_index = signal.index + 1
        if entry_index >= len(bars):
            continue
        entry = bars[entry_index].open * (1 + slippage_bps / 10000)
        stop = signal.invalidation
        exit_index = min(entry_index + horizon_bars, len(bars) - 1)
        exit_price = bars[exit_index].close
        outcome = "horizon"
        for j in range(entry_index, exit_index + 1):
            if bars[j].low <= stop:
                exit_index, exit_price, outcome = j, stop, "stop"
                break
        risk = max(entry - stop, entry * 0.001)
        net_return = (exit_price * (1 - slippage_bps / 10000) / entry) - 1 - (commission_bps * 2 / 10000)
        trades.append(
            Trade(
                signal.pattern,
                entry_index,
                exit_index,
                entry,
                exit_price,
                risk,
                net_return,
                net_return / (risk / entry),
                outcome,
            )
        )
    if not trades:
        return BacktestReport("INSUFFICIENT", (), None, None, None, None, (), "UNKNOWN", "no_complete_trades")
    rs = tuple(trade.r_multiple for trade in trades)
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for trade in trades:
        equity *= 1 + trade.net_return
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
    wins = [value for value in rs if value > 0]
    losses = [value for value in rs if value <= 0]
    return BacktestReport(
        "PASS",
        tuple(trades),
        sum(trade.net_return for trade in trades) / len(trades),
        len(wins) / len(rs),
        sum(wins) / len(wins) if wins else 0.0,
        sum(losses) / len(losses) if losses else 0.0,
        abs(max_drawdown),
        rs,
        "UNASSESSED",
    )
