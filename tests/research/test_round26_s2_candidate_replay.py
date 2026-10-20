import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import round26_s2_candidate_replay as s2


class CandidateReplayTests(unittest.TestCase):
    def test_higher_timeframe_lookup_is_strictly_prior(self):
        times = pd.date_range("2024-01-02 10:00", periods=2, freq="min", tz="America/New_York")
        frame = pd.DataFrame({"time_key": times, "value": [1, 2]})
        self.assertEqual(s2._latest_before(frame, times[1]).value, 1)

    def test_breakout_compares_against_prior_only_features(self):
        row = pd.Series({"close": 101.0, "volume": 121.0, "prior_high20": 100.0, "prior_volume_mean20": 100.0})
        self.assertTrue(s2._breakout(row))
        row["volume"] = 120.0
        self.assertFalse(s2._breakout(row))

    def test_costs_and_cash_equity_identity(self):
        times = pd.date_range("2024-01-02 10:00", periods=4, freq="min", tz="America/New_York")
        signal = {"symbol": "AAPL", "sector": "TECH", "signal_time": times[0],
                  "confirm_5m_time": times[0], "confirm_1m_time": times[0],
                  "entry_time": times[1], "entry_price": 100.0, "stop_price": 95.0,
                  "target_price": 110.0, "exit_time": times[3], "exit_price": 102.0,
                  "exit_reason": "TIME_80_BARS", "risk_per_share": 5.0}
        trades, curve = s2.portfolio_replay([signal], {"AAPL": pd.Series([100, 100, 101, 102], index=times)}, 5.0)
        self.assertEqual(float(trades.iloc[0].units), 50.0)
        expected = 50 * 102 * 0.9995 - 50 * 100 * 1.0005
        self.assertAlmostEqual(float(trades.iloc[0].net_pnl), expected, places=8)
        self.assertLess((curve.equity - curve.cash - curve.holdings_market_value).abs().max(), 1e-8)

    def test_bad_ohlc_and_nonmonotonic_rows_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            pd.DataFrame({"time_key": ["2024-01-02 10:01", "2024-01-02 10:00"],
                          "open": [1, 1], "high": [1, 1], "low": [1, 1],
                          "close": [1, 1], "volume": [1, 1]}).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "not strictly ordered"):
                s2.read_bars(path, "America/New_York", "5m")
            pd.DataFrame({"time_key": ["2024-01-02 10:00"], "open": [1], "high": [1],
                          "low": [1], "close": [2], "volume": [1]}).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "invalid OHLC"):
                s2.read_bars(path, "America/New_York", "5m")

    def test_incomplete_one_minute_session_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            times = pd.date_range("2024-01-02 09:31", periods=3, freq="min")
            pd.DataFrame({"time_key": times, "open": [1] * 3, "high": [1] * 3,
                          "low": [1] * 3, "close": [1] * 3, "volume": [0] * 3}).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "unexpected RTH 1m session endpoints"):
                s2.read_bars(path, "America/New_York", "1m")


if __name__ == "__main__":
    unittest.main()
