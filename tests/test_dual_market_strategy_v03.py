import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v03 import STRATEGIES, build_returns, lagged_trend_weights, max_drawdown, metric_row


def test_fixed_candidates_sum_to_one():
    index = pd.date_range("2020-01-01", periods=3, freq="B")
    for selected in STRATEGIES.values():
        assert np.isclose(sum(selected.values()), 1.0)


def test_cost_uses_initial_turnover_and_bps():
    index = pd.date_range("2020-01-01", periods=2, freq="B")
    prices = pd.DataFrame({"US.QQQ": [100, 100], "US.BTAL": [100, 101], "US.IEF": [100, 100], "US.SHV": [1, 1]}, index=index)
    weights = pd.DataFrame({"US.QQQ": [0.35, 0.35], "US.BTAL": [0.25, 0.25], "US.IEF": [0.25, 0.25], "US.SHV": [0.15, 0.15]}, index=index)
    returns, turnover = build_returns(prices, weights, fee_bps=5, slippage_bps=5)
    assert np.isclose(turnover.iloc[0], 1.0)
    assert np.isclose(returns.iloc[0], -0.001)


def test_trend_signal_is_lagged():
    index = pd.date_range("2019-01-01", periods=300, freq="B")
    qqq = pd.Series(np.linspace(100, 160, len(index)), index=index)
    weights = lagged_trend_weights(index, qqq)
    assert weights.index.equals(index)
    assert np.allclose(weights.sum(axis=1), 1.0)


def test_metrics_include_tail_pressure_and_drawdown():
    index = pd.date_range("2020-01-01", periods=4, freq="B")
    returns = pd.Series([0.01, -0.02, 0.01, 0.0], index=index)
    row = metric_row("x", returns, returns, pd.Series(0.0, index=index), "TRAIN", "5bp")
    assert row["max_drawdown"] == max_drawdown(returns)
    assert "qqq_down_1pct_portfolio_up_rate" in row
