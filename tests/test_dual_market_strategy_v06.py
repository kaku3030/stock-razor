import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v06 import (
    COSTS, FORMAL_START, PHASES, STRATEGIES, metric_row, recovery_days,
)


def test_v06_has_three_fixed_fully_invested_strategies_and_two_costs():
    assert set(STRATEGIES) == {"A_LOW_DRAWDOWN", "B_UPSIDE_HEDGE", "C_BALANCED_COMPOUND"}
    assert all(np.isclose(sum(weights.values()), 1.0) for weights in STRATEGIES.values())
    assert COSTS == ((5, 5, "5bp_fee_5bp_slippage"), (10, 10, "10bp_fee_10bp_slippage"))


def test_recovery_days_is_measured_from_drawdown_trough_to_prior_peak_reclaim():
    index = pd.date_range("2020-01-01", periods=5, freq="B")
    assert recovery_days(pd.Series([.10, -.20, .05, .10, .10], index=index)) == 3.0


def test_metric_row_exposes_risk_recovery_month_and_trade_fields():
    index = pd.date_range("2020-01-01", periods=40, freq="B")
    result = metric_row("x", pd.Series(.001, index=index), pd.Series(-.001, index=index),
                        pd.Series(.1, index=index), "2020", "5bp_fee_5bp_slippage")
    assert {"cagr", "max_drawdown", "calmar", "recovery_days", "worst_day", "worst_month", "trade_count"} <= result.keys()
    assert result["trade_count"] == 40


def test_formal_start_and_windows_never_claim_pre_inception_history():
    assert FORMAL_START == "2006-10-04"
    assert min(start for start, _ in PHASES.values()) == FORMAL_START
    assert PHASES["2025_2026"][1] == "2026-10-16"
