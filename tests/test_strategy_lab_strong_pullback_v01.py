from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.services.strategy_lab.strong_pullback_v01 import (
    Bar,
    InstrumentKind,
    Pattern,
    Provenance,
    Signal,
    qualify_data,
    run_backtest,
    detect_signals,
)


def _bar(i, close, *, low=None, volume=100.0):
    low = close if low is None else low
    return Bar(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * i), close, close + 0.01, low, close, volume)


def _provenance(**changes):
    values = dict(instrument=InstrumentKind.CN_ETF, provider="tickflow", feed="history", timezone="Asia/Shanghai", pit_verified=True, survivorship_controlled=True, source_lineage="tickflow:recorded:sha256")
    values.update(changes)
    return Provenance(**values)


def test_data_qualification_fails_closed_without_provenance():
    result = qualify_data(_provenance(pit_verified=False), (_bar(1, 10),))
    assert result.status == "BLOCKED"
    assert "pit_not_verified" in result.reasons


def test_data_qualification_does_not_treat_us_source_as_cn_tickflow():
    result = qualify_data(_provenance(provider="alpaca"), (_bar(1, 10),))
    assert result.status == "BLOCKED"


def test_forming_bar_is_rejected():
    try:
        _ = Bar(datetime(2026, 1, 1, tzinfo=timezone.utc), 1, 2, 1, 1.5, 10, closed=False)
    except ValueError as exc:
        assert "forming" in str(exc)
    else:
        raise AssertionError("forming bar must not enter research strategy")


def test_backtest_enters_next_bar_and_applies_costs():
    bars = tuple(_bar(i, 10 + i * 0.1) for i in range(8))
    signal = Signal(Pattern.A_FIRST_OR_SECOND_PULLBACK, 1, bars[1].end, 10.1, 9.8, 9.6, 1, ())
    report = run_backtest(bars, (signal,), commission_bps=10, slippage_bps=10, horizon_bars=2, settlement="T+0", market_timezone="UTC")
    assert report.status == "PASS"
    assert report.trades[0].entry_index == 2
    assert report.expected_value < 0.05
    assert report.win_rate == 1.0


def test_backtest_reports_insufficient_sample_without_inventing_metrics():
    report = run_backtest((_bar(0, 10),), (), settlement="T+0", market_timezone="UTC")
    assert report.status == "INSUFFICIENT"
    assert report.expected_value is None
    assert report.win_rate is None


def _context():
    daily = tuple(_bar(i, 10.0 if i < 19 else 11.0, volume=1000) for i in range(20))
    hourly = tuple(_bar(i, 10.0 if i < 19 else 11.0, volume=500) for i in range(20))
    return daily, hourly


def test_a_signal_is_closed_and_classifies_first_pullback():
    daily, hourly = _context()
    bars = [_bar(i, 10.0, low=9.8, volume=100) for i in range(20)]
    bars.extend([_bar(20, 9.95, low=9.9, volume=50), _bar(21, 9.96, low=9.9, volume=50), _bar(22, 9.97, low=9.9, volume=50), _bar(23, 10.3, low=10.0, volume=100)])
    signals = detect_signals(daily=daily, hourly=hourly, fifteen_minute=tuple(bars), provenance=_provenance())
    a_signals = [signal for signal in signals if signal.pattern is Pattern.A_FIRST_OR_SECOND_PULLBACK]
    assert len(a_signals) == 1
    assert a_signals[0].pullback_number == 1
    assert a_signals[0].invalidation < a_signals[0].support_or_breakout


def test_b_acceptance_requires_a_prior_closed_retest():
    daily, hourly = _context()
    bars = [_bar(i, 10.0, low=9.8, volume=100) for i in range(20)]
    bars.extend([_bar(20, 11.0, low=11.0, volume=160), _bar(21, 11.0, low=11.0, volume=100), _bar(22, 11.02, low=11.0, volume=100), _bar(23, 11.3, low=11.1, volume=160)])
    signals = detect_signals(daily=daily, hourly=hourly, fifteen_minute=tuple(bars), provenance=_provenance())
    assert any(signal.pattern is Pattern.B_BREAKOUT_ACCEPTANCE for signal in signals)


def test_c_requires_range_and_volume_contraction_before_breakout():
    daily, hourly = _context()
    bars = [_bar(i, 10.0, low=9.8, volume=100) for i in range(20)]
    bars.extend([_bar(20, 10.1, low=10.0, volume=70), _bar(21, 10.1, low=10.0, volume=70), _bar(22, 10.1, low=10.0, volume=70), _bar(23, 10.1, low=10.0, volume=70), _bar(24, 10.1, low=10.0, volume=70), _bar(25, 10.4, low=10.1, volume=120)])
    signals = detect_signals(daily=daily, hourly=hourly, fifteen_minute=tuple(bars), provenance=_provenance())
    assert any(signal.pattern is Pattern.C_CONTRACTION_BREAKOUT for signal in signals)



def test_backtest_fail_closed_without_explicit_settlement():
    bars = tuple(_bar(i, 10 + 0.1 * i) for i in range(8))
    signal = Signal(Pattern.A_FIRST_OR_SECOND_PULLBACK, 1, bars[1].end, 10.1, 9.8, 9.6, 1, ())
    report = run_backtest(bars, (signal,))
    assert report.status == "BLOCKED"


def test_future_daily_context_does_not_create_past_a_signal():
    daily, hourly = _context()
    bars = [_bar(i, 10.0, low=9.8, volume=100) for i in range(20)]
    bars.extend([_bar(20, 9.95, low=9.9, volume=50), _bar(21, 9.96, low=9.9, volume=50), _bar(22, 9.97, low=9.9, volume=50), _bar(23, 10.3, low=10.0, volume=100)])
    future_daily = tuple(daily[:-1]) + (
        Bar(bars[23].end + timedelta(days=1), 11, 11.01, 10.99, 11, 1000),
    )
    assert detect_signals(daily=future_daily, hourly=hourly, fifteen_minute=tuple(bars), provenance=_provenance()) == ()
    # Earlier signal decisions must not change if later data is appended.
    past = detect_signals(daily=daily, hourly=hourly, fifteen_minute=tuple(bars), provenance=_provenance())
    extended = tuple(daily) + (Bar(bars[23].end + timedelta(days=1), 5, 5.01, 4.99, 5, 1000),)
    assert detect_signals(daily=extended, hourly=hourly, fifteen_minute=tuple(bars), provenance=_provenance()) == past


def test_t1_cannot_sell_on_entry_day_and_gap_fill_uses_open():
    zone = ZoneInfo("Asia/Shanghai")
    start = datetime(2026, 10, 13, 10, 0, tzinfo=zone)
    def bar(at, o, h, l, c):
        return Bar(at, o, h, l, c, 100)
    bars = (
        bar(start, 10, 10.1, 9.9, 10),
        bar(start + timedelta(minutes=15), 10, 10.1, 9.9, 10),
        bar(start + timedelta(minutes=30), 10, 10.05, 9.8, 9.9),
        bar(start + timedelta(minutes=45), 9.9, 9.95, 9.7, 9.8),
        bar(start + timedelta(days=1), 9.6, 9.65, 9.5, 9.55),
        bar(start + timedelta(days=1, minutes=15), 9.6, 9.7, 9.55, 9.65),
    )
    sig = Signal(Pattern.A_FIRST_OR_SECOND_PULLBACK, 1, bars[1].end, 10, 9.85, 9.85, 1, ())
    t0 = run_backtest(bars, (sig,), settlement="T+0", market_timezone="Asia/Shanghai", horizon_bars=2, commission_bps=0, slippage_bps=0)
    t1 = run_backtest(bars, (sig,), settlement="T+1", market_timezone="Asia/Shanghai", horizon_bars=2, commission_bps=0, slippage_bps=0)
    assert t0.status == t1.status == "PASS"
    assert (t0.trades[0].exit_index, t0.trades[0].exit, t0.trades[0].outcome) == (2, 9.85, "stop")
    assert (t1.trades[0].exit_index, t1.trades[0].exit, t1.trades[0].outcome) == (4, 9.6, "gap_stop")
    assert t1.trades[0].r_multiple < t0.trades[0].r_multiple


def test_overlapping_signals_cannot_double_count_equity():
    bars = tuple(_bar(i, 10 + i * 0.1) for i in range(14))
    sigs = (
        Signal(Pattern.A_FIRST_OR_SECOND_PULLBACK, 1, bars[1].end, 10.1, 9.8, 9.6, 1, ()),
        Signal(Pattern.A_FIRST_OR_SECOND_PULLBACK, 2, bars[2].end, 10.2, 9.8, 9.6, 2, ()),
        Signal(Pattern.A_FIRST_OR_SECOND_PULLBACK, 7, bars[7].end, 10.7, 9.8, 9.6, 3, ()),
    )
    result = run_backtest(bars, sigs, settlement="T+0", market_timezone="UTC", horizon_bars=3)
    assert result.status == "PASS"
    assert [trade.entry_index for trade in result.trades] == [2, 8]


def test_invalid_stop_distance_blocks_instead_of_minimum_risk_clamp():
    bars = tuple(_bar(i, 10 + i * 0.1) for i in range(8))
    sig = Signal(Pattern.A_FIRST_OR_SECOND_PULLBACK, 1, bars[1].end, 10.1, 11, 10.5, 1, ())
    r = run_backtest(bars, (sig,), settlement="T+0", market_timezone="UTC")
    assert r.status == "BLOCKED"
    assert r.reason == "invalid_long_stop_distance"


def test_duplicate_or_unsorted_timestamps_fail_closed():
    p = _provenance()
    bars = (_bar(1, 10), _bar(1, 10.5))
    q = qualify_data(p, bars)
    assert q.status == "BLOCKED"
    assert "bars_not_strictly_increasing" in q.reasons



def test_third_pullback_is_not_labeled_a2():
    daily, hourly = _context()
    bars = [_bar(i, 10.0, low=9.8, volume=100) for i in range(20)]
    for _ in range(3):
        for __ in range(7):
            i = len(bars)
            bars.append(_bar(i, 10.0, low=9.8, volume=100))
        for c in (9.95, 9.96, 9.97):
            i = len(bars)
            bars.append(_bar(i, c, low=9.9, volume=50))
        i = len(bars)
        bars.append(_bar(i, 10.3, low=10.0, volume=100))
    found = detect_signals(
        daily=daily, hourly=hourly, fifteen_minute=tuple(bars),
        provenance=_provenance(),
    )
    ordinals = [x.pullback_number for x in found if x.pattern is Pattern.A_FIRST_OR_SECOND_PULLBACK]
    assert ordinals[:3] == [1, 2, 3]
