import pandas as pd

from tools.research.round16_research import (
    SEVEN_REGIMES,
    build_s1_srvp_signals,
    canonicalize_ledger,
    classify_seven_state,
    compare_protocol_ledgers,
    qualify_s2_coverage,
)


def test_protocol_comparison_reports_first_semantic_difference_after_canonical_sort():
    left = pd.DataFrame([{"protocol": "III", "symbol": "AMD", "signal_time": "2024-01-02", "entry_index": 1, "net_pnl": -1}])
    right = pd.DataFrame([{"protocol": "III", "symbol": "AAPL", "signal_time": "2024-01-01", "entry_index": 1, "net_pnl": 1}])
    result = compare_protocol_ledgers(left, right)
    assert result["status"] == "BLOCKED"
    assert result["first_index"] == 0
    assert result["field"] == "symbol"


def test_canonicalize_ledger_is_stable_and_does_not_rewrite_values():
    frame = pd.DataFrame([
        {"protocol": "III", "symbol": "AMD", "signal_time": "2024-01-02", "entry_index": 1},
        {"protocol": "III", "symbol": "AAPL", "signal_time": "2024-01-01", "entry_index": 1},
    ])
    result = canonicalize_ledger(frame)
    assert result.symbol.tolist() == ["AAPL", "AMD"]
    assert result.entry_index.tolist() == [1, 1]


def test_seven_state_classifier_is_causal_and_has_frozen_labels():
    times = pd.date_range("2024-01-01", periods=25, freq="D")
    base = pd.DataFrame({"time_key": times, "close": 100.0, "high": 101.0, "low": 99.0, "ema20": 101.0, "ema50": 100.0, "ema20_slope": 0.01})
    hourly = base.assign(time_key=pd.date_range("2024-01-01", periods=25, freq="h"))
    assert classify_seven_state(base, hourly, pd.Timestamp("2024-02-01")) == "TREND_UP_STRONG"
    assert set(SEVEN_REGIMES) == {"TREND_UP_STRONG", "TREND_UP_WEAK", "TREND_DOWN_STRONG", "TREND_DOWN_WEAK", "RANGE_WIDE", "RANGE_NARROW", "TRANSITION"}


def test_s2_blocks_without_real_one_minute_file(tmp_path):
    result = qualify_s2_coverage(tmp_path, "AAPL")
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "MISSING_1M_OR_OTHER_TIMEFRAME"


def test_s1_requires_only_srvp_frames():
    times = pd.date_range("2024-01-01", periods=120, freq="h")
    frame = pd.DataFrame({"time_key": times, "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0, "volume": 1000.0})
    frames = {"D1": frame, "1H": frame, "15m": frame, "5m": frame}
    result = build_s1_srvp_signals("AAPL", frames, {tf: tf for tf in frames})
    assert "protocol" in result
    assert set(result.protocol) <= {"S1"}
