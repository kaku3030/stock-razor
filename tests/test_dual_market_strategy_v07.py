import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v07 import (
    CANDIDATES, COSTS, FORMAL_START, metric_row, recovery_days,
)


def test_v07_candidates_are_predeclared_and_fully_invested():
    assert set(CANDIDATES) == {
        "B_UPSIDE_HEDGE", "C_BALANCED_COMPOUND", "D_IALT_HEDGE",
        "E_IALT_DEFENSIVE", "F_BALANCED_DEFENSIVE",
    }
    assert all(np.isclose(sum(weights.values()), 1.0) for weights in CANDIDATES.values())
    assert COSTS == ((5, 5, "5bp_fee_5bp_slippage"), (10, 10, "10bp_fee_10bp_slippage"))


def test_recovery_days_and_metrics_keep_requested_risk_fields():
    index = pd.date_range("2020-01-01", periods=5, freq="B")
    assert recovery_days(pd.Series([.10, -.20, .05, .10, .10], index=index)) == 3.0
    result = metric_row("x", pd.Series(.001, index=index), pd.Series(.1, index=index),
                        pd.Series(.1, index=index), "FULL", COSTS[0][2])
    assert {"cagr", "max_drawdown", "recovery_days", "worst_day", "worst_month", "turnover", "trade_count"} <= result.keys()


def test_formal_boundary_and_observation_window_are_explicit():
    assert FORMAL_START == "2006-10-04"
