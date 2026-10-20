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

    def test_equal_weight_buy_and_hold_matches_round24_method(self):
        times = pd.date_range("2024-01-02 16:00", periods=2, freq="D", tz="America/New_York")
        prepared = {
            "AAPL": {"D1": pd.DataFrame({"time_key": times, "close": [100.0, 110.0]})},
            "QQQ": {"D1": pd.DataFrame({"time_key": times, "close": [200.0, 220.0]})},
        }
        result = s2._buy_hold(prepared, times[0], times[1])
        self.assertAlmostEqual(result["return"], 0.10)
        self.assertAlmostEqual(result["final_equity"], 110_000.0)

    def test_six_strategy_comparison_joins_round24_and_candidate_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = Path(tmp) / "baseline.csv"
            baseline = pd.DataFrame([{
                "strategy": strategy, "window": window, "cost_bps_per_side": 10.0,
                "trades": 10, "net_pnl": 1000.0, "profit_factor": 1.5,
                "max_drawdown_pct": 0.05, "win_rate": 0.6,
                "buy_hold_return": 0.2, "buy_hold_max_drawdown_pct": 0.3,
            } for window in ("full_2019_2026", "oos_2024_2026")
              for strategy in ("S1", "S3", "S4", "S5", "S6")])
            baseline.to_csv(baseline_path, index=False)
            candidate = pd.DataFrame([{
                "strategy": "S2_CANDIDATE", "window": window, "cost_bps_per_side": 10.0,
                "trades": 4, "net_pnl": 250.0, "profit_factor": 1.2,
                "max_drawdown_pct": 0.02, "win_rate": 0.5,
            } for window in ("full_2019_2026", "train_2019_2023", "oos_2024_2026")])
            comparison = s2.six_strategy_comparison(candidate, baseline_path)
            self.assertEqual(len(comparison), 14)
            c = comparison[(comparison.strategy == "S2_CANDIDATE") & (comparison.window == "oos_2024_2026")].iloc[0]
            self.assertEqual(c.status, "CANDIDATE_UNVALIDATED")
            self.assertEqual(c.trades, 4)
            bh = comparison[comparison.strategy == "BUY_HOLD_EQUAL_WEIGHT"].iloc[0]
            self.assertEqual(bh.net_pnl, 20_000.0)

    def test_bad_ohlc_and_nonmonotonic_rows_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            pd.DataFrame({"time_key": ["2024-01-02 10:01", "2024-01-02 10:00"],
                          "open": [1, 1], "high": [1, 1], "low": [1, 1],
                          "close": [1, 1], "volume": [1, 1]}).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "not strictly ordered"):
                s2.read_bars(path, "America/New_York", "5m", "AAPL")
            pd.DataFrame({"time_key": ["2024-01-02 10:00"], "open": [1], "high": [1],
                          "low": [1], "close": [2], "volume": [1]}).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "invalid OHLC"):
                s2.read_bars(path, "America/New_York", "5m", "AAPL")

    def test_incomplete_one_minute_session_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            times = pd.date_range("2024-01-02 09:31", periods=3, freq="min")
            pd.DataFrame({"time_key": times, "open": [1] * 3, "high": [1] * 3,
                          "low": [1] * 3, "close": [1] * 3, "volume": [0] * 3}).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "unexpected RTH 1m session endpoints"):
                s2.read_bars(path, "America/New_York", "1m", "AAPL")

    def test_known_cohr_anomaly_requires_explicit_whole_session_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cohr.csv"
            times = pd.date_range("2025-02-11 09:31", periods=390, freq="min")
            frame = pd.DataFrame({"time_key": times, "open": [92.0] * 390, "high": [92.1] * 390,
                                  "low": [91.9] * 390, "close": [92.0] * 390, "volume": [22.0] * 390})
            frame.loc[0, ["open", "high", "low", "close", "volume"]] = [91.67, 91.67, 91.67, 93.66, 22.0]
            frame.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "invalid OHLC"):
                s2.read_bars(path, "America/New_York", "1m", "COHR")
            excluded = s2.read_bars(path, "America/New_York", "1m", "COHR", "2025-02-11")
            self.assertTrue(excluded.empty)
            self.assertEqual(excluded.attrs["excluded_session_rows"], 390)

    def test_unverified_bar_start_semantics_cannot_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "bar-end timestamps"):
                s2.run(Path(tmp), Path(tmp) / "out", "America/New_York", "start")


if __name__ == "__main__":
    unittest.main()
