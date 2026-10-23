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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
    """Contract validation only. External provider evidence must be attested separately."""
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
    if any(bar.end.tzinfo is None or not bar.closed for bar in bars):
        reasons.append("unclosed_or_naive_bar")
    if any(bars[i].end >= bars[i + 1].end for i in range(len(bars) - 1)):
        reasons.append("bars_not_strictly_increasing")
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
    """Research signals using ONLY the closed context known at each trigger time.

    Passing a populated daily/hourly array is NOT permission to look ahead.
    Callers must supply genuine bar-END timestamps and independent provenance.
    """
    for frame in (daily, hourly, fifteen_minute):
        if qualify_data(provenance, frame).status != "PASS":
            return ()
    signals: list[Signal] = []
    pullback_ordinal = 0
    for i in range(20, len(fifteen_minute)):
        bars = fifteen_minute[: i + 1]
        current = bars[-1]
        # The last D1/60m bar in the INPUT may be from the future. NEVER use it
        # to qualify a historical 15m signal. A partially formed bar is forbidden.
        asof_daily = [bar for bar in daily if bar.end <= current.end]
        asof_hourly = [bar for bar in hourly if bar.end <= current.end]
        if not _trend_ok(asof_daily, asof_hourly):
            pullback_ordinal = 0
            continue
        prior = bars[-21:-1]
        baseline_volume = _mean_volume(prior[-10:-3])
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
                    Pattern.C_CONTRACTION_BREAKOUT, i, current.end, current.close,
                    base_high, base_low, None,
                    ("range_contraction", "volume_contraction", "closed_breakout"),
                )
            )
            continue

        pullback = bars[-4:-1]
        if len(pullback) == 3:
            # Structural support must be computed BEFORE the proposed pullback.
            support = min(bar.low for bar in prior[-10:-3])
            quiet = _mean_volume(pullback) <= baseline_volume * 0.8
            shallow = min(bar.low for bar in pullback) >= support * 0.985
            reclaim = current.close > max(bar.high for bar in pullback) and current.volume >= baseline_volume
            if quiet and shallow and reclaim:
                pullback_ordinal += 1
                signals.append(
                    Signal(
                        Pattern.A_FIRST_OR_SECOND_PULLBACK, i, current.end,
                        current.close, support, support * 0.985, pullback_ordinal,
                        ("asof_daily_and_60m_trend", "3_bar_shallow_low",
                         "volume_contraction", "closed_reclaim"),
                    )
                )
                continue

        breakout = max(bar.high for bar in prior)
        accepted = any(
            bar.low >= breakout * 0.99 and bar.close >= breakout * 0.995
            for bar in bars[-4:-1]
        )
        if current.close > breakout and current.volume >= baseline_volume * 1.5 and accepted:
            signals.append(
                Signal(
                    Pattern.B_BREAKOUT_ACCEPTANCE, i, current.end, current.close,
                    breakout, breakout * 0.99, None,
                    ("prior_high_break", "volume_expansion", "accepted_retest", "closed_relaunch"),
                )
            )
    return tuple(signals)


def run_backtest(
    bars: Sequence[Bar],
    signals: Iterable[Signal],
    *,
    commission_bps: float = 5.0,
    slippage_bps: float = 5.0,
    horizon_bars: int = 12,
    settlement: str | None = None,
    market_timezone: str | None = None,
) -> BacktestReport:
    """Conservative long-only SINGLE-POSITION research execution model.

    Settlement MUST be explicitly selected per instrument: CN equity ETFs
    normally require T+1, while eligible asset classes can be T+0.
    This function does not independently certify instrument eligibility.
    Values are researched outcomes, not executable orders or OOS evidence.
    """
    invalid = BacktestReport(
        "BLOCKED", (), None, None, None, None, None, (), "UNKNOWN",
        "invalid_backtest_inputs",
    )
    if (
        not bars or commission_bps < 0 or slippage_bps < 0
        or not isfinite(commission_bps) or not isfinite(slippage_bps)
        or horizon_bars < 1
        or settlement not in ("T+0", "T+1")
        or not market_timezone
    ):
        return invalid
    try:
        tz = ZoneInfo(market_timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return invalid
    if any(not bar.closed for bar in bars) or any(
        bars[i].end >= bars[i + 1].end for i in range(len(bars) - 1)
    ):
        return invalid

    candidates = tuple(sorted(signals, key=lambda signal: signal.index))
    if any(
        sig.index < 0 or sig.index >= len(bars)
        or sig.signal_end != bars[sig.index].end
        for sig in candidates
    ):
        return BacktestReport(
            "BLOCKED", (), None, None, None, None, None, (), "UNKNOWN",
            "signal_index_or_timestamp_invalid",
        )

    trades: list[Trade] = []
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    last_exit = -1
    commission = commission_bps / 10000
    slippage = slippage_bps / 10000

    for signal in candidates:
        entry_index = signal.index + 1
        if entry_index >= len(bars):
            continue
        # No compounding overlapping positions as if each invested 100% equity.
        if entry_index <= last_exit:
            continue
        entry = bars[entry_index].open * (1 + slippage)
        stop = signal.invalidation
        if not isfinite(stop) or stop <= 0 or stop >= entry:
            return BacktestReport(
                "BLOCKED", (), None, None, None, None, None, (), "UNKNOWN",
                "invalid_long_stop_distance",
            )
        entry_day = bars[entry_index].end.astimezone(tz).date()
        def is_sellable(index: int) -> bool:
            return settlement == "T+0" or bars[index].end.astimezone(tz).date() > entry_day

        nominal_end = min(entry_index + horizon_bars, len(bars) - 1)
        exit_index = next(
            (j for j in range(nominal_end, len(bars)) if is_sellable(j)),
            None,
        )
        if exit_index is None:
            # A T+1 position with no next-session data cannot be marked as a
            # realized exit. Exclude it; do not assume same-day liquidation.
            continue
        exit_price = bars[exit_index].close
        outcome = "horizon"
        # The stop is evaluated ONLY once selling is permitted, never by
        # assuming same-day sale for a T+1 CN equity ETF.
        for j in range(entry_index, exit_index + 1):
            if not is_sellable(j):
                continue
            bar = bars[j]
            if bar.open <= stop:
                exit_index, exit_price, outcome = j, bar.open, "gap_stop"
                break
            if bar.low <= stop:
                exit_index, exit_price, outcome = j, stop, "stop"
                break
        # Realistic side-specific entry and exit slippage, both-side commission.
        filled_exit = exit_price * (1 - slippage)
        net_return = filled_exit / entry - 1 - 2 * commission
        risk = entry - stop

        # Chronological mark-to-market close-equity path for disjoint positions.
        # Intrabar peaks/troughs are unknowable from OHLC; no intrabar precision
        # is claimed. The final bar uses the realized fill, not post-exit close.
        before_trade = equity
        entry_equity = before_trade * (1 - commission)
        peak = max(peak, entry_equity)
        max_drawdown = max(max_drawdown, 1 - entry_equity / peak)
        for j in range(entry_index, exit_index):
            mark_equity = entry_equity * (bars[j].close / entry)
            peak = max(peak, mark_equity)
            max_drawdown = max(max_drawdown, 1 - mark_equity / peak)
        equity = before_trade * (1 + net_return)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, 1 - equity / peak)
        last_exit = exit_index
        trades.append(
            Trade(
                signal.pattern, entry_index, exit_index, entry, filled_exit,
                risk, net_return, net_return / (risk / entry), outcome,
            )
        )

    if not trades:
        return BacktestReport(
            "INSUFFICIENT", (), None, None, None, None, None, (),
            "UNKNOWN", "no_complete_trades",
        )
    rs = tuple(trade.r_multiple for trade in trades)
    wins = [value for value in rs if value > 0]
    losses = [value for value in rs if value <= 0]
    return BacktestReport(
        "PASS", tuple(trades),
        sum(trade.net_return for trade in trades) / len(trades),
        len(wins) / len(rs),
        sum(wins) / len(wins) if wins else 0.0,
        sum(losses) / len(losses) if losses else 0.0,
        max_drawdown,
        rs,
        "UNASSESSED",
    )
