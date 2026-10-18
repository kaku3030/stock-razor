import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v11 import (
    CANDIDATES, _episodes, nav_ledger, state_path, state_returns,
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


def test_episode_boundaries_use_previous_observed_row_not_calendar_day():
    dates = pd.DatetimeIndex(["2024-03-08 16:00", "2024-03-11 16:00",
                              "2024-03-12 16:00", "2024-03-15 16:00",
                              "2024-03-18 16:00"],
                             tz="America/New_York")
    states = pd.Series(["NEUTRAL", "RISK_ON", "RISK_ON", "DEFENSIVE", "DEFENSIVE"], index=dates)
    turnover = pd.Series(0.0, index=dates)
    returns = pd.Series([0.0, 0.01, -0.02, 0.03, -0.01], index=dates)
    episodes = _episodes(states, turnover, returns)
    assert episodes[["start", "end", "days"]].to_dict("records") == [
        {"start": "2024-03-08", "end": "2024-03-08", "days": 1},
        {"start": "2024-03-11", "end": "2024-03-12", "days": 2},
        {"start": "2024-03-15", "end": "2024-03-18", "days": 2},
    ]
    assert pd.to_datetime(episodes["end"]).dt.dayofweek.isin([5, 6]).sum() == 0

    holiday_gap = pd.DatetimeIndex(["2024-01-12", "2024-01-16", "2024-01-17"])
    holiday_states = pd.Series(["NEUTRAL", "RISK_ON", "DEFENSIVE"], index=holiday_gap)
    holiday_episodes = _episodes(holiday_states, pd.Series(0.0, index=holiday_gap),
                                 pd.Series(0.0, index=holiday_gap))
    assert holiday_episodes.loc[0, "end"] == "2024-01-12"


def test_nav_ledger_reconciles_daily_return_and_preserves_unclosed_final_episode():
    prices = _prices(8)
    ledger = nav_ledger(prices, CANDIDATES["V10_BASELINE"], 5, 5)
    realized = ledger["nav"] / ledger["start_nav"] - 1.0
    assert (realized - ledger["net_return"]).abs().max() < 1e-12
    assert ledger.index[-1] == prices.index[-1]
    assert ledger["end_weight_US.SHV"].iloc[-1] >= 0.0
