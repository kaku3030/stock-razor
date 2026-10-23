import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v04 import (
    annual_metrics,
    pressure_metrics,
    rolling_forward_metrics,
    strategy_definitions,
    tail_risk_decomposition,
)


def test_focus_definitions_are_fixed_and_fully_invested():
    definitions = strategy_definitions()
    assert {"QQQ_TAIL_IEF_SHV", "QQQ_USMV_IEF_SHV", "TREND_QQQ_BTAL_IEF_SHV"} <= definitions.keys()
    for name, weights in definitions.items():
        if not name.startswith("TREND_"):
            assert np.isclose(sum(weights.values()), 1.0)


def test_annual_and_pressure_metrics_are_year_partitioned():
    index = pd.date_range("2020-12-30", periods=5, freq="B")
    portfolio = pd.Series([0.01, -0.02, 0.01, 0.02, -0.03], index=index)
    qqq = pd.Series([0.02, -0.01, -0.02, 0.01, -0.03], index=index)
    turnover = pd.Series(0.1, index=index)
    annual = annual_metrics(portfolio, qqq, turnover, "x", "5bp")
    pressure = pressure_metrics(portfolio, qqq, "x", "5bp")
    assert {row["year"] for row in annual} == {2020, 2021}
    assert {row["threshold"] for row in pressure} == {0.01, 0.02, 0.03}


def test_rolling_forward_never_uses_future_training_rows():
    index = pd.date_range("2020-01-01", "2022-12-31", freq="B")
    portfolio = pd.Series(0.001, index=index)
    qqq = pd.Series(0.001, index=index)
    turnover = pd.Series(0.0, index=index)
    rows = rolling_forward_metrics(portfolio, qqq, turnover, "x", "5bp")
    assert [row["forward_year"] for row in rows] == [2021, 2022]
    assert all(row["train_end"] < row["forward_start"] for row in rows)


def test_tail_decomposition_handles_qqq_benchmark_column_without_collision():
    index = pd.date_range("2020-01-01", periods=4, freq="B")
    prices = pd.DataFrame({"US.QQQ": [100, 101, 99, 100], "US.TAIL": [100, 100.5, 101, 100.8]}, index=index)
    weights = pd.DataFrame({"US.QQQ": 0.35, "US.TAIL": 0.65}, index=index)
    rows = tail_risk_decomposition(prices, weights)
    assert {row["asset"] for row in rows} == {"US.QQQ", "US.TAIL"}
