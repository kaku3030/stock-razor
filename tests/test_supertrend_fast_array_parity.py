"""Numerical parity regression for the array-backed SuperTrend hot path.

The Pandas scalar reference is deliberately slow and local to the test. We
must never sacrifice entry/exit technical evidence semantics for speed.
"""
import numpy as np
import pandas as pd
import pytest

from src.technical.indicators import add_atr, add_supertrend


def _scalar_reference(df, *, period=10, multiplier=3.0):
    result = add_atr(df, period)
    midpoint = (result["high"] + result["low"]) / 2
    upper = midpoint + multiplier * result[f"atr{period}"]
    lower = midpoint - multiplier * result[f"atr{period}"]
    direction = pd.Series(1, index=result.index, dtype=int)
    line = lower.copy()
    for index in range(1, len(result)):
        previous = index - 1
        if result.at[index, "close"] > upper.at[previous]:
            direction.at[index] = 1
        elif result.at[index, "close"] < lower.at[previous]:
            direction.at[index] = -1
        else:
            direction.at[index] = direction.at[previous]
            if direction.at[index] > 0:
                lower.at[index] = max(lower.at[index], lower.at[previous])
            else:
                upper.at[index] = min(upper.at[index], upper.at[previous])
        line.at[index] = lower.at[index] if direction.at[index] > 0 else upper.at[index]
    result["supertrend"] = line
    result["supertrend_direction"] = direction
    return result


def _frame(rows, *, seed=0, drift=0):
    rng = np.random.default_rng(seed)
    close = 160 + np.cumsum(rng.normal(drift, 1, rows))
    spread = rng.uniform(0, 3, rows)
    return pd.DataFrame({
        "open": close.copy(),
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "volume": rng.integers(1, 1000, rows),
    })


@pytest.mark.parametrize("bars", [0, 1, 2, 3, 9, 20, 60, 120, 480])
@pytest.mark.parametrize("drift", [-0.6, 0, 0.6])
def test_numpy_supertrend_is_exactly_identical_to_scalar_reference(bars, drift):
    for seed in (0, 1, 17):
        candles = _frame(bars, seed=seed, drift=drift)
        expected = _scalar_reference(candles)
        optimized = add_supertrend(candles)
        pd.testing.assert_frame_equal(optimized, expected, check_exact=True)
        assert "supertrend_direction" in optimized
        assert list(optimized.columns) == list(expected.columns)


@pytest.mark.parametrize("period,multiplier", [(1, 0.1), (7, 1.5), (10, 3.0), (14, 4.5)])
def test_multiple_atr_periods_and_multipliers_preserve_reference(period, multiplier):
    candles = _frame(250, seed=21)
    expected = _scalar_reference(candles, period=period, multiplier=multiplier)
    result = add_supertrend(candles, period=period, multiplier=multiplier)
    pd.testing.assert_frame_equal(result, expected, check_exact=True)


def test_no_change_in_nan_and_zero_volume_behavior():
    candles = _frame(100, seed=12)
    candles.loc[10, "high"] = float("nan")
    candles.loc[20, "low"] = float("nan")
    candles.loc[31, "close"] = float("nan")
    candles.loc[40, "volume"] = 0
    candles.loc[55:57, "close"] = candles.loc[54, "close"]
    expected = _scalar_reference(candles)
    actual = add_supertrend(candles)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)


def test_supertrend_works_on_nonconsecutive_index_without_mutating_input():
    candles = _frame(50, seed=2)
    original = candles.copy(deep=True)
    candles.index = pd.Index(np.arange(100, 150) * 2)
    before = candles.copy(deep=True)
    actual = add_supertrend(candles)
    assert len(actual) == len(candles)
    assert actual.index.equals(candles.index)
    pd.testing.assert_frame_equal(candles, before, check_exact=True)
    assert len(actual["supertrend_direction"]) == 50
    pd.testing.assert_frame_equal(original, before.reset_index(drop=True), check_exact=True)


def test_supertrend_stays_a_fact_not_an_order_decision():
    candles = _frame(480, seed=9)
    result = add_supertrend(candles)
    assert set(result["supertrend_direction"].unique()).issubset({-1, 1})
    assert all(str(column).lower() not in {"order", "live_trade", "trade_action"} for column in result.columns)
