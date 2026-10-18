import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v11 import (
    CANDIDATES, state_path, state_returns,
)


def _prices(days=180):
    dates = pd.date_range("2020-01-01", periods=days, freq="B")
    return pd.DataFrame({
        "US.QQQ": np.linspace(100, 70, days),
        "US.SCHD": np.linspace(100, 85, days),
        "US.GLD": np.linspace(100, 105, days),
        "US.SHV": np.linspace(100, 100.2, days),
    }, index=dates)


def test_candidates_are_finite_and_predeclared():
    assert set(CANDIDATES) == {"V10_BASELINE", "LAYERED_DRAWDOWN", "SLOW_REENTRY"}
    assert CANDIDATES["LAYERED_DRAWDOWN"]["neutral_drawdown"] == -0.10
    assert CANDIDATES["SLOW_REENTRY"]["risk_on_days"] == 20


def test_state_signal_is_causal_and_next_day_effective_contract_holds():
    prices = _prices()
    original = state_path(prices, CANDIDATES["V10_BASELINE"])
    changed = prices.copy()
    changed.iloc[-1, changed.columns.get_loc("US.QQQ")] = 1.0
    assert original.iloc[:-1].equals(state_path(changed, CANDIDATES["V10_BASELINE"]).iloc[:-1])


def test_returns_include_costs_and_state_trace():
    returns, turnover, states = state_returns(_prices(), CANDIDATES["V10_BASELINE"], 5, 5)
    assert len(returns) == len(turnover) == len(states)
    assert turnover.iloc[0] == 1.0
    assert set(states).issubset({"RISK_ON", "NEUTRAL", "DEFENSIVE"})
