import numpy as np
import pandas as pd
import pytest

from tools.research.dual_market_accounting import replay_portfolio, target_schedule


def _prices():
    return pd.DataFrame(
        {"A": [100.0, 110.0, 121.0, 120.0], "B": [100.0, 100.0, 100.0, 110.0]},
        index=pd.date_range("2024-01-02", periods=4, freq="B"),
    )


def test_static_portfolio_drifts_without_implicit_daily_rebalance():
    prices = _prices()
    target, rebalance = target_schedule(prices, {"A": 0.5, "B": 0.5})
    ledger = replay_portfolio(prices, target, rebalance, 0, 0)
    assert ledger["rebalanced"].tolist() == [True, False, False, False]
    assert ledger["turnover"].tolist() == [1.0, 0.0, 0.0, 0.0]
    assert ledger["actual_weight_A"].iloc[1] == pytest.approx(110 / 210)
    assert ledger["actual_weight_A"].iloc[2] == pytest.approx(121 / 221)


def test_state_change_rebalances_and_conserves_nav():
    prices = _prices()
    states = pd.Series(["RISK_ON", "RISK_ON", "DEFENSIVE", "DEFENSIVE"], index=prices.index)
    target, rebalance = target_schedule(
        prices,
        {},
        state=states,
        state_weights={"RISK_ON": {"A": 1.0}, "DEFENSIVE": {"B": 1.0}},
    )
    ledger = replay_portfolio(prices, target, rebalance, 5, 5)
    assert ledger["rebalanced"].tolist() == [True, False, True, False]
    assert (ledger["nav"] - ledger["start_nav"] * (1 + ledger["net_return"])).abs().max() < 1e-12
    assert (ledger["actual_weight_A"] + ledger["actual_weight_B"] + ledger["cash_weight"]).round(12).eq(1).all()
    cheaper = replay_portfolio(prices, target, rebalance, 0, 0)
    assert ledger["nav"].iloc[-1] <= cheaper["nav"].iloc[-1]


def test_missing_nonfinite_and_future_rows_fail_closed():
    prices = _prices()
    target, rebalance = target_schedule(prices, {"A": 1.0, "B": 0.0})
    bad = prices.copy()
    bad.iloc[2, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        replay_portfolio(bad, target, rebalance, 0, 0)
    changed = prices.copy()
    changed.iloc[-1, 0] = np.inf
    with pytest.raises(ValueError, match="finite"):
        replay_portfolio(changed, target, rebalance, 0, 0)
    with pytest.raises(ValueError, match="first row"):
        replay_portfolio(prices, target, rebalance & ~rebalance.index.isin([prices.index[0]]), 0, 0)
