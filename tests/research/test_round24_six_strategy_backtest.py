import pandas as pd

from tools.research import round11_radar_research as r11
from tools.research.round24_six_strategy_backtest import _vectorized_curve


def test_vectorized_curve_matches_existing_cash_and_mark_to_market_accounting():
    times = pd.date_range("2024-01-02 10:00", periods=4, freq="5min")
    prepared = {
        "AAPL": {
            "5m": pd.DataFrame({
                "time_key": times,
                "close": [10.0, 11.0, 12.0, 13.0],
            })
        }
    }
    trades = pd.DataFrame([{
        "symbol": "AAPL",
        "entry_time": times[0],
        "exit_time": times[2],
        "entry_price": 10.0,
        "exit_price": 12.0,
        "units": 10.0,
    }])

    r11.COST_BPS = 10.0
    expected = r11._portfolio_curve(trades, prepared)
    actual = _vectorized_curve(trades, prepared, 10.0)

    for column in ("cash", "holdings_market_value", "unrealized_pnl",
                   "total_equity", "drawdown", "accounting_residual"):
        pd.testing.assert_series_equal(
            actual[column], expected[column], check_names=False, check_dtype=False
        )
