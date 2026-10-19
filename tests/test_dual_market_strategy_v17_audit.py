import pandas as pd
import pytest

from tools.research.dual_market_strategy_v17_audit import _rates, _summary


def test_capture_uses_explicit_benchmark_return_denominators():
    index = pd.date_range("2024-01-02", periods=4, freq="B")
    strategy = pd.Series([0.02, -0.01, 0.01, 0.03], index=index)
    qqq = pd.Series([0.01, -0.02, 0.02, -0.01], index=index)
    result = _rates(strategy, qqq)
    assert result["benchmark_up_return_denominator"] == pytest.approx(0.03)
    assert result["benchmark_down_return_denominator"] == pytest.approx(-0.03)
    assert result["benchmark_up_capture"] == pytest.approx(1.0)
    assert result["benchmark_down_capture"] == pytest.approx(-2 / 3)
    assert result["benchmark_down_day_strategy_positive_rate"] == pytest.approx(0.5)


def test_summary_exposes_monthly_positive_rate_denominator():
    index = pd.date_range("2024-01-02", periods=4, freq="B")
    strategy = pd.Series([0.01, 0.0, -0.01, 0.02], index=index)
    qqq = pd.Series([0.01, -0.01, 0.01, -0.01], index=index)
    result = _summary(strategy, qqq, "X", "daily")
    assert result["n_periods"] == 4
    assert result["positive_period_rate"] == pytest.approx(0.5)


def test_monthly_cagr_uses_twelve_periods_per_year():
    index = pd.date_range("2024-01-31", periods=12, freq="ME")
    strategy = pd.Series([0.01] * 12, index=index)
    qqq = pd.Series([0.0] * 12, index=index)
    result = _summary(strategy, qqq, "X", "monthly")
    assert result["cagr"] == pytest.approx((1.01 ** 12) - 1.0)


def test_summary_rejects_unknown_frequency():
    index = pd.date_range("2024-01-02", periods=1, freq="B")
    values = pd.Series([0.01], index=index)
    with pytest.raises(ValueError, match="unsupported summary frequency"):
        _summary(values, values, "X", "weekly")
