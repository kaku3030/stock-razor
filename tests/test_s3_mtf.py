"""Synthetic adversarial cases, never historical-performance evidence."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.services.strategy_lab.s3_mtf import (
    Rules, aggregate, build_signals, features, metrics, planned_loss, replay, validate_input,
)


def session(day="2024-03-08", close="16:00"):
    tz = "America/New_York"
    return pd.DataFrame({"open_at": [pd.Timestamp(f"{day} 09:30", tz=tz)],
                         "close_at": [pd.Timestamp(f"{day} {close}", tz=tz)]})


def candles(s, price=100.):
    ends = [t for r in s.itertuples() for t in pd.date_range(
        r.open_at+pd.Timedelta(minutes=5), r.close_at, freq="5min")]
    return pd.DataFrame(dict(end=ends, open=price, high=price+.2, low=price-.2,
                             close=price, volume=100.))


def signal(when="2024-03-08 09:40:01-05:00", arm="B", stop=95., max_entry=101.):
    return pd.DataFrame([dict(decision_at=pd.Timestamp(when),
                              signal_end=pd.Timestamp(when)-pd.Timedelta(seconds=1),
                              d1_end=pd.Timestamp(when)-pd.Timedelta(days=1),
                              structure_end=pd.Timestamp(when)-pd.Timedelta(hours=4),
                              setup_end=pd.Timestamp(when)-pd.Timedelta(hours=4), signal_close=100.,
                              stop=stop, max_entry=max_entry, arm=arm)])


def test_4h_bins_stubs_and_volume_conserve():
    s = session()
    b = candles(s)
    h = aggregate(b, s, 240)
    assert h.duration_minutes.tolist() == [240, 150]
    assert h.stub.tolist() == [False, True]
    assert h.end.dt.tz_convert("America/New_York").dt.strftime("%H:%M").tolist() == ["13:30", "16:00"]
    assert h.volume.sum() == b.volume.sum()
    assert (h.available_at > h.end).all()


def test_early_close_not_fictitious_4h():
    s = session("2024-11-29", "13:00")
    h = aggregate(candles(s), s, 240)
    assert h.duration_minutes.tolist() == [210]
    assert h.stub.tolist() == [True]


def test_dst_anchoring():
    s = pd.concat([session(), session("2024-03-11")], ignore_index=True)
    h = aggregate(candles(s), s, 240)
    assert h.start.dt.hour.tolist() == [14, 18, 13, 17]


@pytest.mark.parametrize("mode", ["missing_bar", "missing_day", "duplicate", "future", "bad_ohlc", "nan"])
def test_corrupt_or_incomplete_paths_fail_entire_scenario(mode):
    s = pd.concat([session(), session("2024-03-11")], ignore_index=True)
    b = candles(s)
    if mode == "missing_bar": b = b.drop(index=5)
    elif mode == "missing_day": b = b.iloc[:78]
    elif mode == "duplicate": b.loc[5, "end"] = b.loc[4, "end"]
    elif mode == "future": b.loc[len(b)-1, "end"] += pd.Timedelta(minutes=5)
    elif mode == "bad_ohlc": b.loc[5, "high"] = 90.
    elif mode == "nan": b.loc[5, "low"] = np.nan
    with pytest.raises(ValueError): validate_input(b, s)


def test_naive_timestamps_rejected():
    s = session()
    b = candles(s)
    b["end"] = b.end.dt.tz_localize(None)
    with pytest.raises(ValueError, match="OFFSET"): aggregate(b, s, 240)


def test_true_range_includes_gaps():
    f = pd.DataFrame(dict(close=[100.]*14+[120.], high=[101.]*14+[121.], low=[99.]*14+[119.]))
    assert features(f).atr14.iloc[-1] == pytest.approx((13*2+21)/14)


def test_a_cannot_be_impersonated_by_proxy():
    with pytest.raises(ValueError, match="A_BLOCKED"):
        build_signals(candles(session()), session(), "A")


def test_first_fill_strictly_after_availability_and_risk_includes_both_cost_sides():
    s, r = session(), replace(Rules(), first_risk_fraction=1.)
    b = candles(s)
    trades, events, curve = replay({"X":b}, s, {"X":signal()}, {"X":"TECH"}, rules=r)
    e = events[events.reason == "ENTRY"].iloc[0]
    assert e.time == pd.Timestamp("2024-03-08 09:45-05:00")
    assert e.units == int(250/planned_loss(100., 95., .001))
    assert e.campaign_risk <= 250.
    assert trades.net_pnl.sum() == pytest.approx(curve.equity.iloc[-1]-100000.)


def test_stop_wins_same_bar_target_and_gap_gets_worse_price():
    s, b = session(), candles(session())
    b.loc[3, ["high", "low"]] = [115., 94.]
    t, _, _ = replay({"X":b}, s, {"X":signal()}, {"X":"TECH"})
    assert t.exit_reason.tolist() == ["STOP"]
    assert t.exit_price.tolist() == [95.]
    b = candles(s)
    b.loc[5, ["open", "high", "low", "close"]] = [90., 91., 89., 90.]
    t, _, _ = replay({"X":b}, s, {"X":signal()}, {"X":"TECH"})
    assert t.exit_price.tolist() == [90.]
    assert t.net_pnl.iloc[0] < -t.budget.iloc[0]*.4


def test_no_first_fill_after_chase_or_gap_through_stop():
    s, b = session(), candles(session())
    for stop, ceiling, reason in [(101., 102., "GAP_THROUGH_STOP"), (95., 99., "CHASE_LIMIT")]:
        t, e, _ = replay({"X":b}, s, {"X":signal(stop=stop, max_entry=ceiling)}, {"X":"TECH"})
        assert t.empty
        assert e.reason.tolist() == [reason]


def test_second_leg_never_uses_same_close_and_shares_fixed_budget():
    s, b = session(), candles(session())
    # 10:30 hour closes at +1R, but the bar OPEN at 10:30 precedes 10:30:01.
    b.loc[10:, ["open", "close"]] = 106.
    b.loc[10:, "high"] = 106.2
    b.loc[10:, "low"] = 105.8
    _, e, _ = replay({"X":b}, s, {"X":signal()}, {"X":"TECH"})
    adds = e[e.reason == "ADD"]
    # Hourly ATR needs 14 bars; a one-day fixture deliberately cannot qualify.
    assert adds.empty


def test_qualified_add_shares_budget_and_waits_for_next_eligible_open(monkeypatch):
    # Isolate execution from the separately tested daily qualification layer.
    monkeypatch.setattr("src.services.strategy_lab.s3_mtf.daily_allowed", lambda *_: True)
    s = pd.concat([session("2024-03-06"), session("2024-03-07"), session()], ignore_index=True)
    b = candles(s)
    b.loc[166:, ["open", "close"]] = 106.
    b.loc[166:, "high"] = 106.2
    b.loc[166:, "low"] = 105.8
    _, e, _ = replay({"X":b}, s, {"X":signal()}, {"X":"TECH"})
    adds = e[e.reason == "ADD"]
    assert len(adds) == 1
    assert adds.time.iloc[0] == pd.Timestamp("2024-03-08 10:35-05:00")
    assert adds.campaign_risk.iloc[0] <= adds.campaign_budget.iloc[0]


@pytest.mark.parametrize("key", ["d1_end", "structure_end", "setup_end"])
def test_future_high_timeframe_evidence_cannot_fill(key):
    ss = signal()
    ss[key] = ss.decision_at + pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match="FUTURE"):
        replay({"X":candles(session())}, session(), {"X":ss}, {"X":"TECH"})


def test_zero_trades_is_not_positive_performance_or_infinite_pf():
    s, b = session(), candles(session())
    t, _, c = replay({"X":b}, s, {"X":pd.DataFrame()}, {"X":"TECH"})
    m = metrics(t, c)
    assert m["trades"] == 0 and m["total_return"] == 0
    assert m["profit_factor"] is None and m["cagr"] is None


def test_numeric_strings_do_not_bypass_ohlc_shape():
    s = session()
    b = candles(s).astype({k:str for k in ("open", "high", "low", "close", "volume")})
    b.loc[3, "high"] = "90"
    with pytest.raises(ValueError, match="OHLCV"):
        validate_input(b, s)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1.5, True, 0])
def test_invalid_count_caps_fail_closed(value):
    with pytest.raises(ValueError, match="COUNT"):
        replace(Rules(), max_positions=value)


def test_existing_target_gap_cancels_pending_add(monkeypatch):
    monkeypatch.setattr("src.services.strategy_lab.s3_mtf.daily_allowed", lambda *_: True)
    s = pd.concat([session("2024-03-06"), session("2024-03-07"), session()], ignore_index=True)
    b = candles(s)
    b.loc[166:168, ["open", "close"]] = 101.5
    b.loc[166:168, "high"] = 101.6
    b.loc[166:168, "low"] = 101.4
    b.loc[169:, ["open", "close"]] = 103.
    b.loc[169:, "high"] = 103.1
    b.loc[169:, "low"] = 102.9
    t, e, _ = replay({"X":b}, s, {"X":signal(stop=99.)}, {"X":"TECH"})
    assert "ADD" not in e.reason.tolist()
    assert t.exit_reason.tolist() == ["GAP_TARGET_LIMIT"]
    assert t.exit_price.tolist() == [102.]


def test_window_uses_prior_history_but_no_pre_window_positions(monkeypatch):
    monkeypatch.setattr("src.services.strategy_lab.s3_mtf.daily_allowed", lambda *_: True)
    s = pd.concat([session("2024-03-06"), session("2024-03-07"), session()], ignore_index=True)
    b = candles(s)
    b.loc[166:, ["open", "close"]] = 106.
    b.loc[166:, "high"] = 106.2
    b.loc[166:, "low"] = 105.8
    ss = pd.concat([signal("2024-03-06 09:40:01-05:00"), signal()])
    t, e, c = replay({"X":b}, s, {"X":ss}, {"X":"TECH"},
                      trade_start=s.open_at.iloc[-1], trade_end=s.close_at.iloc[-1])
    assert len(t) == 1
    assert len(e[e.reason == "ADD"]) == 1
    assert len(c) == 78


def test_d_has_no_1h_add_dependency(monkeypatch):
    monkeypatch.setattr("src.services.strategy_lab.s3_mtf.daily_allowed", lambda *_: True)
    s = pd.concat([session("2024-03-06"), session("2024-03-07"), session()], ignore_index=True)
    b = candles(s)
    b.loc[166:, ["open", "close"]] = 106.
    b.loc[166:, "high"] = 106.2
    b.loc[166:, "low"] = 105.8
    _, e, _ = replay({"X":b}, s, {"X":signal(arm="D")}, {"X":"TECH"})
    # Only six 4H/stub observations: no ATR14 on D's decision frame.
    assert len(e[e.reason == "ADD"]) == 0


def test_preflight_never_reports_missing_data_as_backtested(tmp_path):
    import json
    import subprocess
    import sys
    manifest = dict(history_reused=True, symbols=[dict(symbol="X", path="missing.csv")],
                    schedule=dict(path="missing_schedule.csv"), benchmark=dict(path="missing_qqq.csv"))
    path = tmp_path/"input.json"
    path.write_text(json.dumps(manifest))
    result = subprocess.run([sys.executable, "scripts/run_s3_mtf_research.py", "--manifest", str(path),
                             "--output", str(tmp_path/"out"), "--preflight-only"],
                            capture_output=True, text=True, check=True)
    status = json.loads(result.stdout)
    assert status["status"] == "BLOCKED" and status["matrix_complete"] is False
    assert status["reason"] == "RAW_INPUTS_MISSING"
    assert not (tmp_path/"out"/"metrics.csv").exists()


def test_qqq_benchmark_charges_both_sides():
    import importlib.util
    spec = importlib.util.spec_from_file_location("s3_runner", "scripts/run_s3_mtf_research.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    m, _ = runner.benchmark(candles(session()), 100000., 10.)
    assert m["total_return"] == pytest.approx(.999/1.001-1)
    with pytest.raises(ValueError, match="PARTIAL_SESSION"):
        runner.select_window(session(), pd.Timestamp("2024-03-08 10:00-05:00"),
                              pd.Timestamp("2024-03-08 16:00-05:00"))


def synthetic_history(model="pullback"):
    """Artificial weekdays/prices, deliberately NOT a real XNYS history."""
    sessions, rows = [], []
    for i, day in enumerate(pd.bdate_range("2023-01-02", periods=220)):
        s = session(str(day.date()))
        sessions.append(s)
        x = candles(s)
        x["close"] = 100*1.003**i*(1+.001*np.arange(78)/78)
        if model == "pullback":
            if i == 214: x.loc[48:, "close"] *= .987
            if i == 215:
                x.loc[:47, "close"] *= .978
                x.loc[48:, "close"] *= .99
        else:
            level = 100*1.003**209*(1+.001*77/78)+.02
            if 210 <= i <= 213: x["close"] = level-.02
            if i == 214:
                x.loc[:47, "close"] = level+3.
                x.loc[48:, "close"] = level+.02
            if i == 215: x["close"] = level+.4
        x["open"] = x.close
        x["high"], x["low"] = x.close+.02, x.close-.02
        rows.append(x)
    return pd.concat(rows, ignore_index=True), pd.concat(sessions, ignore_index=True)


def test_pullback_and_retest_have_sequential_closed_evidence():
    for model, arm in [("pullback", "B"), ("retest", "C")]:
        b, s = synthetic_history(model)
        x = build_signals(b, s, arm)
        assert len(x) > 0
        assert (x.setup_end < x.signal_end).all()
        assert (x.d1_end < x.decision_at).all()
        assert (x.structure_end < x.decision_at).all()


def test_future_prices_do_not_change_past_signals():
    b, s = synthetic_history()
    before = build_signals(b, s, "B")
    b.loc[b.end>s.close_at.iloc[-3], ["open", "high", "low", "close"]] *= 100
    after = build_signals(b, s, "B")
    cutoff = s.close_at.iloc[-3]
    pd.testing.assert_frame_equal(before[before.decision_at<=cutoff].reset_index(drop=True),
                                  after[after.decision_at<=cutoff].reset_index(drop=True))


def test_complete_cli_smoke_is_labelled_partial_matrix_not_five_group_result(tmp_path):
    import hashlib
    import json
    import subprocess
    import sys
    b, s = synthetic_history()
    b.to_csv(tmp_path/"bars.csv", index=False)
    s.to_csv(tmp_path/"schedule.csv", index=False)
    sha = lambda name: hashlib.sha256((tmp_path/name).read_bytes()).hexdigest()
    item = dict(symbol="X", sector="TEST", path="bars.csv", sha256=sha("bars.csv"),
                label="end", timezone="UTC", timestamp_column="end", source="SYNTHETIC_TEST_ONLY", price_basis="SYNTHETIC")
    manifest = dict(history_reused=True, symbols=[item], benchmark=dict(item, symbol="QQQ"),
                    schedule=dict(path="schedule.csv", sha256=sha("schedule.csv")),
                    windows=[dict(name="SYNTHETIC_SMOKE", start=s.open_at.iloc[210].isoformat(), end=s.close_at.iloc[-1].isoformat())])
    (tmp_path/"manifest.json").write_text(json.dumps(manifest))
    result = subprocess.run([sys.executable, "scripts/run_s3_mtf_research.py", "--manifest", str(tmp_path/"manifest.json"),
                             "--output", str(tmp_path/"out")], capture_output=True, text=True, check=True)
    status = json.loads(result.stdout)
    assert status["status"] == "PARTIAL_MATRIX_REPLAYED_RESEARCH_ONLY"
    assert status["matrix_complete"] is False and status["promotion"] == "NO"
    result_table = pd.read_csv(tmp_path/"out"/"metrics.csv")
    assert len(result_table) == 20
    assert set(result_table.arm) == {"B", "C", "D", "E", "QQQ_BH"}
