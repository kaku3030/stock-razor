import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v08 import (
    CANDIDATES, COSTS, FORMAL_START, monthly_rebalanced_returns, metric_row,
)


def test_fixed_candidates_and_listing_boundary_are_explicit():
    assert set(CANDIDATES) == {
        "QQQ_SCHD_GLD_50_30_20", "QQQ_SCHD_GLD_40_30_30", "QQQ_SCHD_GLD_60_20_20",
        "QQQ_ONLY", "LONG_GOLD_50_50", "LONG_GOLD_40_30_30",
        "B_UPSIDE_HEDGE", "C_BALANCED_COMPOUND", "F_BALANCED_DEFENSIVE",
    }
    assert all(np.isclose(sum(weights.values()), 1.0) for weights in CANDIDATES.values())
    assert COSTS == ((5, 5, "5bp_fee_5bp_slippage"), (10, 10, "10bp_fee_10bp_slippage"))
    assert FORMAL_START == "2006-10-04"


def test_monthly_rebalance_records_initial_and_month_change_turnover():
    index = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-02-03"])
    prices = pd.DataFrame({"US.QQQ": [100, 101, 102], "US.GLD": [100, 100, 101]}, index=index)
    returns, turnover = monthly_rebalanced_returns(prices, {"US.QQQ": .5, "US.GLD": .5}, 5, 5)
    assert len(returns) == 3
    assert turnover.iloc[0] == 1.0
    assert turnover.iloc[2] >= 0.0


def test_metric_row_contains_requested_risk_and_participation_fields():
    index = pd.date_range("2020-01-01", periods=5, freq="B")
    result = metric_row("x", pd.Series(.001, index=index), pd.Series(.1, index=index),
                        pd.Series(.1, index=index), "FULL", COSTS[0][2])
    assert {"cagr", "max_drawdown", "recovery_days", "calmar", "sharpe", "worst_day",
            "worst_month", "monthly_turnover", "qqq_up_day_follow_rate",
            "qqq_down_day_countertrend_up_rate"} <= result.keys()
