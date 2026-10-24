from dataclasses import replace

import pandas as pd
import pytest

from src.services.strategy_lab.s3_mtf import Rules, replay


def fixture():
    start=pd.Timestamp("2024-03-08 09:30",tz="America/New_York")
    schedule=pd.DataFrame(dict(open_at=[start],close_at=[start+pd.Timedelta(minutes=390)]))
    bars=pd.DataFrame(dict(end=pd.date_range(start+pd.Timedelta(minutes=5),periods=78,freq="5min"),
                           open=100.,high=100.2,low=99.8,close=100.,volume=100.))
    sig=pd.DataFrame([dict(arm="A",decision_at=start+pd.Timedelta(minutes=10,seconds=1),
                          signal_end=start+pd.Timedelta(minutes=10),d1_end=start-pd.Timedelta(days=1),
                          structure_end=start,setup_end=start,signal_close=100.,stop=95.,max_entry=1e100)])
    return schedule,bars,sig


def test_legacy_bar_cap_uses_a_causal_future_open_and_keeps_original_daily_exit_policy():
    s,b,ss=fixture()
    rules=replace(Rules(),first_risk_fraction=1.,max_sessions=1000000)
    t,_,_=replay({"X":b},s,{"X":ss},{"X":"T"},rules=rules,
                  max_holding_bars=2,exit_on_daily_filter=False)
    assert t.exit_at.iloc[0]==pd.Timestamp("2024-03-08 10:00",tz="America/New_York")
    assert t.exit_reason.iloc[0]=="CLOSED_BAR_EXIT"
    # Entry09:45, firstbar ends09:50, secondbar09:55, decision09:55:01;
    # opening09:55 is already past, so 10:00 is the first eligible open.


@pytest.mark.parametrize("cap",[0,-1,True,float("nan"),1.5])
def test_legacy_invalid_holding_cap_is_not_an_unbounded_run(cap):
    s,b,ss=fixture()
    with pytest.raises(ValueError,match="BAR_CAP"):
        replay({"X":b},s,{"X":ss},{"X":"T"},max_holding_bars=cap)
