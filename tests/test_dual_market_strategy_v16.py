import pandas as pd
import pytest

from tools.research.dual_market_accounting import replay_portfolio, target_schedule
from tools.research.dual_market_strategy_v10 import state_path
from tools.research.dual_market_strategy_v16 import A_WEIGHTS, B_DYNAMIC_WEIGHTS, FORWARD_WINDOWS, _blend


def test_a_weights_and_blend_conserve_cash_budget():
    assert sum(A_WEIGHTS.values()) == pytest.approx(1.0)
    assert sum(_blend(A_WEIGHTS, {"US.QQQ": .5, "US.SHV": .5}).values()) == pytest.approx(1.0)


def test_missing_price_is_fail_closed_before_replay():
    prices = pd.DataFrame({"US.QQQ": [100.0, 101.0]}, index=pd.date_range("2024-01-01", periods=2))
    with pytest.raises(KeyError):
        prices[["US.QQQ", "US.KMLM"]]


def test_accounting_cash_and_costs_are_conservative():
    prices = pd.DataFrame({"US.QQQ": [100.0, 110.0], "US.SHV": [100.0, 100.0]}, index=pd.date_range("2024-01-01", periods=2))
    targets, rebalance = target_schedule(prices, {"US.QQQ": .5, "US.SHV": .5})
    free = replay_portfolio(prices, targets, rebalance, 0, 0)
    cost = replay_portfolio(prices, targets, rebalance, 5, 5)
    assert (free["cash"] >= 0).all()
    assert cost.iloc[0].nav < free.iloc[0].nav


def test_forward_windows_are_fixed_and_non_overlapping():
    windows = list(FORWARD_WINDOWS.values())
    assert all(start < end for start, end in windows)
    assert all(windows[i][1] < windows[i + 1][0] for i in range(len(windows) - 1))


def test_ab_comparison_requires_all_a_and_b_assets():
    a_symbols = set(A_WEIGHTS)
    b_symbols = {symbol for weights in B_DYNAMIC_WEIGHTS.values() for symbol in weights}
    assert a_symbols | b_symbols >= {"US.QQQ", "US.SCHD", "US.KMLM", "US.GLD", "US.DBMF", "US.BTAL"}


def test_state_path_does_not_use_future_rows():
    index = pd.date_range("2020-01-01", periods=140, freq="B")
    base = pd.DataFrame({"US.QQQ": range(100, 240), "US.SCHD": range(100, 240)}, index=index).astype(float)
    changed = base.copy()
    changed.iloc[-1] *= 100.0
    assert state_path(base).iloc[:-1].equals(state_path(changed).iloc[:-1])


def test_state_rebalance_frequency_is_state_change_only():
    index = pd.date_range("2024-01-01", periods=4, freq="B")
    prices = pd.DataFrame({"US.QQQ": [100, 101, 99, 100], "US.SHV": [100, 100, 100, 100]}, index=index)
    states = pd.Series(["NEUTRAL", "NEUTRAL", "DEFENSIVE", "DEFENSIVE"], index=index)
    targets, rebalance = target_schedule(prices, {}, state=states, state_weights={"NEUTRAL": {"US.QQQ": .5}, "DEFENSIVE": {"US.SHV": .5}})
    assert int(rebalance.sum()) == 2
    assert targets.loc[index[1], "US.QQQ"] == pytest.approx(.5)
