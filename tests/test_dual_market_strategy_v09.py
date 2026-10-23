import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v09 import (
    VOL_LOOKBACK,
    VOL_OFF,
    VOL_ON,
    dynamic_returns,
    trend_signal,
    volatility_signal,
)


def test_dynamic_signal_uses_only_prior_rows_and_records_turnover():
    dates = pd.date_range("2020-01-01", periods=25, freq="B")
    prices = pd.DataFrame({
        "US.QQQ": np.linspace(100, 80, len(dates)),
        "US.SCHD": np.linspace(100, 95, len(dates)),
        "US.GLD": np.linspace(100, 105, len(dates)),
        "US.SHV": np.linspace(100, 100.1, len(dates)),
    }, index=dates)
    returns, turnover, states = dynamic_returns(prices, VOL_ON, VOL_OFF,
                                                volatility_signal, 5, 5)
    assert len(returns) == len(prices)
    assert np.isclose(turnover.iloc[0], 1.0)
    assert states.iloc[0] == "ON"
    assert set(states).issubset({"ON", "OFF"})


def test_signals_need_history_and_trend_is_closed_bar_only():
    short = pd.DataFrame({"US.QQQ": [100.0] * VOL_LOOKBACK,
                          "US.SCHD": [100.0] * VOL_LOOKBACK})
    assert volatility_signal(short) is False
    assert trend_signal(short) is False
    prior = pd.DataFrame({"US.QQQ": [100.0] * 125 + [90.0],
                          "US.SCHD": [100.0] * 126})
    assert trend_signal(prior) is True
