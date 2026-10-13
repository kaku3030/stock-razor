from datetime import datetime, timedelta, timezone

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
    report = run_backtest(bars, (signal,), commission_bps=10, slippage_bps=10, horizon_bars=2)
    assert report.status == "PASS"
    assert report.trades[0].entry_index == 2
    assert report.expected_value < 0.05
    assert report.win_rate == 1.0


def test_backtest_reports_insufficient_sample_without_inventing_metrics():
    report = run_backtest((_bar(0, 10),), ())
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
