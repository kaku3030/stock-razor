from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json

import pandas as pd
import pytest

from data_provider.cn_tickflow_research_cache import (
    SCHEMA,normalize_bars,build_observation,atomic_publish,read_cn_tickflow_research_data,
)

SH=ZoneInfo("Asia/Shanghai")
NOW=datetime(2026,10,11,5,0,tzinfo=timezone.utc)  # Sunday: historical research only
TIMES={
 "15m":("09:45","10:00","10:15","10:30","10:45","11:00",
         "11:15","11:30","13:15","13:30","13:45","14:00",
         "14:15","14:30","14:45","15:00"),
 "60m":("10:30","11:30","14:00","15:00"),
}

def frame(period,day="2026-10-09"):
    rows=[]
    for h in TIMES[period]:
        stamp=datetime.fromisoformat(f"{day}T{h}").replace(tzinfo=SH)
        rows.append(dict(timestamp=int(stamp.timestamp())*1000,open=1.5,high=1.7,
                low=1.3,close=1.6,volume=1000,amount=1600,
                credential="SECRET_SHOULD_NOT_LEAK"))
    return pd.DataFrame(rows)

class FakeKlines:
    def __init__(self):
        self.calls=[]
    def get(self,symbol,*,period,count,as_dataframe,adjust):
        self.calls.append((symbol,period,count,as_dataframe,adjust))
        df = frame(period)
        return {key: df[key].tolist() for key in
                ("timestamp","open","high","low","close","volume","amount")}

class FakeClient:
    def __init__(self):
        self.klines=FakeKlines()

def test_tickflow_source_worker_builds_bounded_bars_without_unqualified_claims(tmp_path):
    fake=FakeClient()
    snap=build_observation(fake,now_utc=NOW,repo_sha="a"*40,sequence=3)
    assert snap["provider"]=="TICKFLOW_PREMIUM"
    assert snap["source_arbiter_admission"]=="BLOCKED"
    assert snap["radar_admission"]=="BLOCKED"
    assert snap["canonical_write_authorized"] is False
    assert snap["live_trade"] is False
    assert len(fake.klines.calls)==4
    assert [x[2] for x in fake.klines.calls]==[96,24,96,24]
    assert all(x[3] is False and x[4]=="none" for x in fake.klines.calls)
    assert "SECRET_SHOULD_NOT_LEAK" not in json.dumps(snap)
    for sym in ("159611.SZ","518880.SH"):
        for period in ("15m","60m"):
            bars=snap["symbols"][sym][period]["rows"]
            assert len(bars)==len(TIMES[period])
            assert all(x["is_partial_bar"] and x["bar_finality"]=="NOT_VERIFIED" for x in bars)
    dest=tmp_path/"obs.json"
    atomic_publish(str(dest),snap)
    row=read_cn_tickflow_research_data("159611.SZ","15m",5,path=str(dest),now_utc=NOW)
    assert row["ok"] is True
    assert len(row["rows"])==5
    assert row["provider_requests"]==0
    assert row["can_confirm_signal"] is False
    assert row["currentness"]=="UNPROVEN"
    assert "SECRET_SHOULD_NOT_LEAK" not in json.dumps(row)

def test_data_reader_does_not_allow_stale_file_or_promoted_admission(tmp_path):
    dest=tmp_path/"obs.json"
    snap=build_observation(FakeClient(),now_utc=NOW,repo_sha="f"*40,sequence=1)
    atomic_publish(str(dest),snap)
    late=read_cn_tickflow_research_data("159611.SZ","15m",path=str(dest),
             now_utc=NOW+timedelta(seconds=181))
    assert late["status"]=="STALE" and late["ok"] is False
    snap["source_arbiter_admission"]="PASS"
    atomic_publish(str(dest),snap)
    wrong=read_cn_tickflow_research_data("159611.SZ","15m",path=str(dest),now_utc=NOW)
    assert wrong["status"]=="INVALID_CACHE"

def test_current_forming_candle_is_never_closed_even_if_timestamp_elapsed():
    bars=normalize_bars(frame("15m","2026-10-09"),"15m",now_utc=NOW)
    assert all(x["bar_finality"]=="NOT_VERIFIED" for x in bars)
    assert all(x["is_partial_bar"] for x in bars)

@pytest.mark.parametrize("edit", [
    lambda df:df.assign(timestamp=df.timestamp+5000),
    lambda df:df.assign(volume=-1),
    lambda df:df.assign(open=float("nan")),
    lambda df:df.iloc[::-1].reset_index(drop=True),
    lambda df:df.assign(high=0.1),
])
def test_invalid_tickflow_payload_fails_closed(edit):
    with pytest.raises(ValueError):
        normalize_bars(edit(frame("15m")),"15m",now_utc=NOW)

def test_future_label_fails_closed():
    with pytest.raises(ValueError):
        normalize_bars(frame("15m","2026-10-14"),"15m",now_utc=NOW)

def test_nonlisted_symbol_and_bad_inputs_fail_closed(tmp_path):
    obj=build_observation(FakeClient(),now_utc=NOW,repo_sha="f"*40,sequence=1)
    p=tmp_path/"obs.json"
    atomic_publish(str(p),obj)
    for sym in ("AMD","000001","159611.sz","518880.BJ"):
        r=read_cn_tickflow_research_data(sym,path=str(p),now_utc=NOW)
        assert r["status"]=="INVALID_REQUEST"
    assert read_cn_tickflow_research_data("159611.SZ",limit=0,path=str(p),now_utc=NOW)["status"]=="INVALID_REQUEST"

def test_tampered_bar_finality_is_rejected(tmp_path):
    obj=build_observation(FakeClient(),now_utc=NOW,repo_sha="f"*40,sequence=1)
    obj["symbols"]["159611.SZ"]["15m"]["rows"][-1]["bar_finality"]="PROVEN"
    p=tmp_path/"obs.json"
    atomic_publish(str(p),obj)
    assert read_cn_tickflow_research_data("159611.SZ",path=str(p),now_utc=NOW)["status"]=="INVALID_CACHE"


def test_provider_forming_future_bar_is_excluded_not_promoted():
    now=datetime(2026,10,13,5,5,tzinfo=timezone.utc) # Shanghai 13:05
    old=frame("15m","2026-10-09").iloc[:6].copy()
    soon=frame("15m","2026-10-13").iloc[8:9].copy() # 13:15 end, not reached
    merged=pd.concat([old,soon],ignore_index=True)
    out=normalize_bars(merged,"15m",now_utc=now)
    assert len(out)==6
    assert all(x["bar_finality"]=="NOT_VERIFIED" for x in out)
    assert not any(x["label"].startswith("2026-10-13") for x in out)

def test_compact_sdk_missing_or_length_mismatched_columns_fail_closed():
    raw=FakeKlines().get("159611.SZ",period="15m",count=96,as_dataframe=False,adjust="none")
    bad={**raw,"amount":raw["amount"][:-1]}
    with pytest.raises(ValueError,match="lengths differ"):
        normalize_bars(bad,"15m",now_utc=NOW)
    missing={k:v for k,v in raw.items() if k!="timestamp"}
    with pytest.raises(ValueError,match="missing compact"):
        normalize_bars(missing,"15m",now_utc=NOW)


def test_cache_heartbeat_does_not_make_yesterdays_bars_current_in_market():
    # A fresh cache written at 14:00 Shanghai with only previous-day Klines
    # MUST NOT be labeled a usable live-session feed.
    active=datetime(2026,10,13,6,5,tzinfo=timezone.utc)
    snap=build_observation(FakeClient(),now_utc=active,
                           repo_sha="f"*40,sequence=1)
    from tempfile import TemporaryDirectory
    from pathlib import Path
    with TemporaryDirectory() as d:
        p=Path(d)/"o.json"
        atomic_publish(str(p),snap)
        for period in ("15m","60m"):
            v=read_cn_tickflow_research_data("159611.SZ",period,path=str(p),
                                            now_utc=active)
            assert v["ok"] is False
            assert v["status"]=="BAR_LABEL_BEHIND_SESSION"
            assert v["radar_admission"]=="BLOCKED"
            assert v["rows"]==[]


def test_expected_closed_labels_do_not_assert_exchange_bar_finality():
    from data_provider.cn_tickflow_research_cache import _expected_closed_grid_label
    active=datetime(2026,10,13,5,17,tzinfo=timezone.utc)  # Shanghai 13:17
    assert _expected_closed_grid_label(active,"15m").strftime("%H:%M")=="13:15"
    assert _expected_closed_grid_label(active,"60m").strftime("%H:%M")=="11:30"
    first=datetime(2026,10,13,1,37,tzinfo=timezone.utc)  # Shanghai 09:37
    assert _expected_closed_grid_label(first,"15m") is None

def test_unapproved_a_share_scan_or_duplicate_cannot_bypass_billing_whitelist():
    for syms in (("000001.SZ",),("159611.SZ","000001.SZ"),
                 ("159611.SZ","159611.SZ")):
        with pytest.raises(ValueError,match="unapproved symbols"):
            build_observation(FakeClient(),now_utc=NOW,repo_sha="a"*40,
                              sequence=1,symbols=syms)

def test_current_session_offgrid_start_label_quarantined_without_false_finality():
    current=datetime(2026,10,13,5,8,tzinfo=timezone.utc) # Shanghai 13:08
    old=frame("15m","2026-10-09").iloc[:7].copy()
    today=frame("15m","2026-10-13").iloc[:1].copy()
    from datetime import datetime as dt
    today.loc[today.index[0],"timestamp"]=int(dt(2026,10,13,13,0,
                                                tzinfo=SH).timestamp()*1000)
    merged=pd.concat([old,today],ignore_index=True)
    rows=normalize_bars({col:merged[col].tolist() for col in
        ("timestamp","open","high","low","close","volume","amount")},
        "15m",now_utc=current)
    assert len(rows)==len(old)
    assert all(x["bar_finality"]=="NOT_VERIFIED" for x in rows)


def test_historical_offgrid_start_label_is_always_rejected():
    old=frame("15m","2026-10-09")
    from datetime import datetime as dt
    old.loc[old.index[0],"timestamp"]=int(dt(2026,10,9,9,30,
                                               tzinfo=SH).timestamp()*1000)
    with pytest.raises(ValueError,match="unexpected Shanghai regular-session grid"):
        normalize_bars({col:old[col].tolist() for col in
            ("timestamp","open","high","low","close","volume","amount")},
            "15m",now_utc=NOW)

def test_sdk_compact_missing_optional_amount_is_null_not_invented():
    now=datetime(2026,10,11,5,0,tzinfo=timezone.utc)
    raw=FakeKlines().get("159611.SZ",period="15m",count=96,
                          as_dataframe=False,adjust="none")
    without_amount={k:v for k,v in raw.items() if k!="amount"}
    bars=normalize_bars(without_amount,"15m",now_utc=now)
    assert len(bars)>4
    assert all(x["amount"] is None
               and x["amount_availability"]=="SDK_OMITTED" for x in bars)
    class MissingAmountKlines:
        def get(self, *args, **kwargs):
            df=frame(kwargs["period"])
            return {key:df[key].tolist() for key in
                    ("timestamp","open","high","low","close","volume")}
    class Client:
        klines=MissingAmountKlines()
    snap=build_observation(Client(),now_utc=now,repo_sha="a"*40,sequence=1)
    from tempfile import TemporaryDirectory
    from pathlib import Path
    with TemporaryDirectory() as d:
        q=Path(d)/"o.json"
        atomic_publish(str(q),snap)
        got=read_cn_tickflow_research_data("159611.SZ",path=str(q),now_utc=now)
        assert got["ok"] is True
        assert all(x["amount"] is None and x["amount_availability"]=="SDK_OMITTED"
                for x in got["rows"])

def test_amount_present_but_null_does_not_falsely_pass_without_contract():
    raw=FakeKlines().get("159611.SZ",period="15m",count=96,
                         as_dataframe=False,adjust="none")
    bad={**raw,"amount":[None]*len(raw["amount"])}
    with pytest.raises(ValueError,match="invalid provider number"):
        normalize_bars(bad,"15m",now_utc=NOW)

def test_current_intraday_invalid_ohlc_is_quarantined_without_faking_finality():
    now=datetime(2026,10,13,5,18,tzinfo=timezone.utc)  # Shanghai 13:18
    old=frame("15m","2026-10-09").iloc[:7].copy()
    today=frame("15m","2026-10-13").iloc[8:9].copy() # 13:15 label
    today.loc[today.index[0],"high"]=0.0
    payload=pd.concat([old,today],ignore_index=True)
    raw={key:payload[key].tolist() for key in
         ("timestamp","open","high","low","close","volume","amount")}
    result=normalize_bars(raw,"15m",now_utc=now)
    assert len(result)==len(old)
    assert all(x["bar_finality"]=="NOT_VERIFIED" for x in result)
    # The same malformed bar in completed historical session is blocked.
    earlier=frame("15m","2026-10-09")
    earlier.loc[earlier.index[0],"high"]=0.0
    invalid={key:earlier[key].tolist() for key in
         ("timestamp","open","high","low","close","volume","amount")}
    with pytest.raises(ValueError,match="invalid OHLCVA nonpositive"):
        normalize_bars(invalid,"15m",now_utc=now)

def test_nonconforming_current_volume_is_quarantined_not_synthetically_repaired():
    now=datetime(2026,10,13,5,18,tzinfo=timezone.utc)
    earlier=frame("60m","2026-10-09").iloc[:4].copy()
    current=frame("60m","2026-10-13").iloc[2:3].copy()
    current.loc[current.index[0],"volume"]=-1
    df=pd.concat([earlier,current],ignore_index=True)
    raw={k:df[k].tolist() for k in
         ("timestamp","open","high","low","close","volume","amount")}
    assert len(normalize_bars(raw,"60m",now_utc=now))==4

def test_last_due_intraday_label_missing_allows_history_but_blocks_session(tmp_path):
    current=datetime(2026,10,13,7,16,tzinfo=timezone.utc) # Shanghai 15:16
    snap=build_observation(FakeClient(),now_utc=current,
            repo_sha="b"*40,sequence=4)
    cache=tmp_path/"cache.json"
    atomic_publish(str(cache),snap)
    strict=read_cn_tickflow_research_data(
        "159611.SZ","15m",path=str(cache),now_utc=current)
    assert strict["status"]=="BAR_LABEL_BEHIND_SESSION"
    assert strict["ok"] is False
    hist=read_cn_tickflow_research_data(
        "159611.SZ","15m",path=str(cache),now_utc=current,
        research_mode="historical_only")
    assert hist["ok"] is True
    assert hist["status"]=="PASS_HISTORICAL_ONLY"
    assert hist["expected_grid_progress"]=="DUE_LABEL_NOT_OBSERVED_HISTORICAL_ONLY"
    assert hist["currentness"]=="UNPROVEN"
    assert hist["session_currentness"]=="NOT_VERIFIED"
    assert hist["bar_finality"]=="NOT_VERIFIED"
    assert hist["radar_admission"]=="BLOCKED"
    assert hist["canonical_write_authorized"] is False
    assert hist["provider_requests"]==0
    assert len(hist["rows"])>0

def test_offsession_cache_refresh_interval_is_explicit_historical_only(tmp_path):
    current=datetime(2026,10,13,7,16,tzinfo=timezone.utc)
    snap=build_observation(FakeClient(),now_utc=current,
            repo_sha="c"*40,sequence=1)
    p=tmp_path/"cache.json"
    atomic_publish(str(p),snap)
    later=current+timedelta(seconds=320)
    strict=read_cn_tickflow_research_data("159611.SZ",
        path=str(p),now_utc=later)
    hist=read_cn_tickflow_research_data("159611.SZ",
        path=str(p),now_utc=later,research_mode="historical_only")
    assert strict["status"]=="STALE"
    assert hist["status"]=="PASS_HISTORICAL_ONLY"
    assert hist["max_age_seconds"]==360
    too_late=read_cn_tickflow_research_data("159611.SZ",
        path=str(p),now_utc=current+timedelta(seconds=370),
        research_mode="historical_only")
    assert too_late["status"]=="STALE"

def test_unrecognized_research_mode_cannot_disable_gates(tmp_path):
    q=read_cn_tickflow_research_data("159611.SZ",
            path=str(tmp_path/"fake"),research_mode="production")
    assert q["status"]=="INVALID_REQUEST"
    assert q["radar_admission"]=="BLOCKED"
    assert q["live_trade"] is False
