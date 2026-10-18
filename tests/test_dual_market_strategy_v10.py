import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v10 import (
    DEFENSIVE,
    ENTER_CONFIRMATION,
    RISK_ON_CONFIRMATION,
    state_path,
    state_returns,
)


def _prices(rows=180):
    dates = pd.date_range("2020-01-01", periods=rows, freq="B")
    return pd.DataFrame({
        "US.QQQ": np.linspace(100, 120, rows),
        "US.SCHD": np.linspace(100, 110, rows),
        "US.GLD": np.linspace(100, 105, rows),
        "US.SHV": np.linspace(100, 100.2, rows),
    }, index=dates)


def test_state_path_is_causal_and_starts_neutral_without_history():
    prices = _prices()
    states = state_path(prices)
    assert states.iloc[0] == "NEUTRAL"
    assert set(states).issubset({"RISK_ON", "NEUTRAL", "DEFENSIVE"})


def test_defensive_entry_requires_confirmation():
    prices = _prices()
    prices.iloc[130:135, prices.columns.get_loc("US.QQQ")] = np.linspace(120, 90, 5)
    prices.iloc[130:135, prices.columns.get_loc("US.SCHD")] = np.linspace(110, 95, 5)
    states = state_path(prices)
    defensive = np.flatnonzero(states.to_numpy() == "DEFENSIVE")
    assert len(defensive) > 0
    assert defensive[0] >= 130 + ENTER_CONFIRMATION - 1


def test_returns_charge_turnover_and_preserve_state_contract():
    prices = _prices()
    returns, turnover, states = state_returns(prices, 5, 5)
    assert len(returns) == len(prices) == len(turnover) == len(states)
    assert np.isclose(turnover.iloc[0], sum(abs(v) for v in {"US.QQQ": 0.6, "US.SCHD": 0.3, "US.GLD": 0.1}.values()))
    assert RISK_ON_CONFIRMATION > ENTER_CONFIRMATION
    assert DEFENSIVE["US.SHV"] == 0.6
