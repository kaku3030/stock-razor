from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json

import pandas as pd
import pytest

from data_provider.cn_tickflow_research_cache import (
    SCHEMA,MAX_SCAN_SYMBOLS,normalize_bars,build_observation,atomic_publish,
    read_cn_tickflow_research_data,resolve_scan_symbols,
)

SH=ZoneInfo("Asia/Shanghai")
TEST_SCAN_SYMBOLS=20
TEST_MAX_SYMBOLS=200
NOW=datetime(2026,10,11,5,0,tzinfo=timezone.utc)  # Sunday: historical research only
TIMES={
 "15m":("09:45","10:00","10:15","10:30","10:45","11:00",
         "11:15","11:30","13:15","13:30","13:45","14:00",
         "14:15","14:30","14:45","15:00"),
 "60m":("10:30","11:30","14:00","15:00"),
}

def frame(period,day="2026-10-09"):
    rows=[]
    clocks = TIMES.get(period, ())
    if period == "1m":
        clocks = ("09:31", "09:32", "09:33", "09:34")
    elif period == "5m":
        clocks = ("09:35", "09:40", "09:45", "09:50")
    elif period == "1d":
        clocks = ("00:00",) * 4
        day = None
    for index,h in enumerate(clocks):
        row_day = day or (datetime.fromisoformat("2026-10-09") -
                          timedelta(days=3-index)).date().isoformat()
        stamp=datetime.fromisoformat(f"{row_day}T{h}").replace(tzinfo=SH)
        rows.append(dict(timestamp=int(stamp.timestamp())*1000,open=1.5,high=1.7,
                low=1.3,close=1.6,volume=1000,amount=1600,
                credential="SECRET_SHOULD_NOT_LEAK"))
    return pd.DataFrame(rows)

class FakeKlines:
    def __init__(self):
        self.calls=[]
        self.batch_calls=[]
        self.intraday_batch_calls=[]
    def get(self,symbol,*,period,count,as_dataframe,adjust):
        self.calls.append((symbol,period,count,as_dataframe,adjust))
        df = frame(period)
        return {key: df[key].tolist() for key in
                ("timestamp","open","high","low","close","volume","amount")}

    def batch(self, symbols, **kwargs):
        self.batch_calls.append((list(symbols), kwargs))
        return {symbol: self.get(
            symbol, period=kwargs["period"], count=kwargs["count"],
            as_dataframe=kwargs["as_dataframe"], adjust=kwargs.get("adjust", "none"),
        ) for symbol in symbols}

    def intraday_batch(self, symbols, **kwargs):
        self.intraday_batch_calls.append((list(symbols), kwargs))
        return {symbol: self.get(
            symbol, period=kwargs["period"], count=kwargs["count"],
            as_dataframe=kwargs["as_dataframe"], adjust="none",
        ) for symbol in symbols}

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
    assert len(fake.klines.calls)==8
    assert [x[2] for x in fake.klines.calls]==[96,24]*4
    assert all(x[3] is False and x[4]=="none" for x in fake.klines.calls)
    assert "SECRET_SHOULD_NOT_LEAK" not in json.dumps(snap)
    for sym in ("159611.SZ","159209.SZ","512730.SH","159363.SZ"):
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

def test_batch_missing_symbols_fall_back_only_for_missing_entries():
    fake=FakeClient()
    original=fake.klines.intraday_batch

    def partial_batch(symbols, **kwargs):
        result=original(symbols, **kwargs)
        if kwargs["period"]=="1m":
            result.pop("159363.SZ")
        return result

    fake.klines.intraday_batch=partial_batch
    snap=build_observation(fake,now_utc=NOW,repo_sha="a"*40,sequence=3,
                           include_supplemental=True,use_batch=True)
    calls=[call for call in fake.klines.calls if call[1]=="1m"]
    assert len(calls)==5
    assert sum(call[0]=="159363.SZ" for call in calls)==2
    assert len(snap["symbols"]["159363.SZ"]["1m"]["rows"])==4
    assert all(row["bar_finality"]=="NOT_VERIFIED"
               for row in snap["symbols"]["159363.SZ"]["1m"]["rows"])


def test_batch_missing_symbol_fallback_failure_fails_closed():
    from scripts.run_cn_tickflow_research_worker import _normalize_rejection_reason

    fake=FakeClient()
    original_get=fake.klines.get

    def partial_batch(symbols, **kwargs):
        result={
            symbol: original_get(
                symbol, period=kwargs["period"], count=kwargs["count"],
                as_dataframe=kwargs["as_dataframe"], adjust="none",
            )
            for symbol in symbols
        }
        if kwargs["period"]=="1m":
            result.pop("159363.SZ")
        return result

    def failing_get(symbol, *, period, count, as_dataframe, adjust):
        if symbol=="159363.SZ" and period=="1m":
            raise RuntimeError("provider failure")
        return original_get(symbol,period=period,count=count,
                            as_dataframe=as_dataframe,adjust=adjust)

    fake.klines.intraday_batch=partial_batch
    fake.klines.get=failing_get
    with pytest.raises(RuntimeError) as caught:
        build_observation(fake,now_utc=NOW,repo_sha="a"*40,sequence=3,
                          include_supplemental=True,use_batch=True)
    assert getattr(caught.value,"_tickflow_stage",None)=="BATCH_1M_SYMBOL_FALLBACK"
    assert _normalize_rejection_reason(caught.value)=="BATCH_SYMBOL_FALLBACK_FAILED"


def test_batch_missing_symbols_across_periods_use_bounded_fallback_budget():
    fake=FakeClient()
    original_intraday=fake.klines.intraday_batch
    original_daily=fake.klines.batch

    def omit_one(method, symbols, **kwargs):
        result=method(symbols, **kwargs)
        result.pop(symbols[0])
        return result

    fake.klines.intraday_batch=lambda symbols, **kwargs: omit_one(
        original_intraday,symbols,**kwargs
    )
    fake.klines.batch=lambda symbols, **kwargs: omit_one(
        original_daily,symbols,**kwargs
    )
    snap=build_observation(fake,now_utc=NOW,repo_sha="a"*40,sequence=3,
                           include_supplemental=True,use_batch=True)
    assert len(fake.klines.calls)==25
    assert all(
        period in observed
        for observed in snap["symbols"].values()
        for period in ("1m","5m","15m","60m","1d")
    )

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


def test_scan_capacity_accepts_twenty_explicit_symbols_and_reader_sees_all(tmp_path):
    symbols = tuple(f"{100000 + index:06d}.SZ" for index in range(TEST_SCAN_SYMBOLS))
    assert resolve_scan_symbols(",".join(symbols)) == symbols
    fake = FakeClient()
    snapshot = build_observation(
        fake, now_utc=NOW, repo_sha="a" * 40, sequence=1,
        symbols=symbols, allow_scan_symbols=True,
    )
    assert tuple(snapshot["symbols"]) == symbols
    assert len(fake.klines.calls) == TEST_SCAN_SYMBOLS * 2
    path = tmp_path / "twenty.json"
    atomic_publish(str(path), snapshot)
    result = read_cn_tickflow_research_data(
        symbols[-1], "15m", path=str(path), now_utc=NOW,
    )
    assert result["ok"] is True
    assert result["radar_admission"] == "BLOCKED"


def test_scan_capacity_covers_twenty_symbols_across_all_five_periods():
    symbols = tuple(f"{100000 + index:06d}.SZ" for index in range(TEST_SCAN_SYMBOLS))
    fake = FakeClient()
    snapshot = build_observation(
        fake, now_utc=NOW, repo_sha="a" * 40, sequence=1,
        symbols=symbols, include_supplemental=True, allow_scan_symbols=True,
    )
    assert len(fake.klines.calls) == TEST_SCAN_SYMBOLS * 5
    assert all(set(snapshot["symbols"][symbol]) ==
               {"1m", "5m", "15m", "60m", "1d"} for symbol in symbols)


def test_full_capacity_uses_one_batch_request_per_period():
    symbols = tuple(f"{100000 + index:06d}.SZ" for index in range(TEST_SCAN_SYMBOLS))
    fake = FakeClient()
    snapshot = build_observation(
        fake, now_utc=NOW, repo_sha="a" * 40, sequence=1,
        symbols=symbols, include_supplemental=True,
        allow_scan_symbols=True, use_batch=True,
    )
    assert len(fake.klines.batch_calls) == 1
    assert len(fake.klines.intraday_batch_calls) == 4
    assert len(snapshot["symbols"]) == TEST_SCAN_SYMBOLS


def test_two_hundred_symbol_batch_capacity_covers_all_five_periods():
    symbols = tuple(f"{100000 + index:06d}.SZ" for index in range(TEST_MAX_SYMBOLS))
    fake = FakeClient()
    snapshot = build_observation(
        fake, now_utc=NOW, repo_sha="a" * 40, sequence=1,
        symbols=symbols, include_supplemental=True,
        allow_scan_symbols=True, use_batch=True,
    )
    assert len(fake.klines.batch_calls) == 1
    assert len(fake.klines.intraday_batch_calls) == 4
    assert len(snapshot["symbols"]) == TEST_MAX_SYMBOLS


@pytest.mark.parametrize("value", [
    "000001.SZ,000001.SZ",
    ",".join(f"{100000 + index:06d}.SZ" for index in range(MAX_SCAN_SYMBOLS + 1)),
    "000001,600000.SH",
])
def test_scan_symbol_parser_fails_closed(value):
    with pytest.raises(ValueError, match="invalid scan symbols"):
        resolve_scan_symbols(value)

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


def test_postclose_session_progress_accepts_bounded_vendor_float_rows(tmp_path):
    """Post-close progress reads keep due-grid visibility without finality."""
    current=datetime(2026,10,14,7,5,tzinfo=timezone.utc)  # Shanghai 15:05
    class CurrentDayKlines:
        def get(self,symbol,*,period,count,as_dataframe,adjust):
            df=frame(period,"2026-10-14")
            if period=="15m":
                df["high"]=1.5999999999999994
            return {key:df[key].tolist() for key in
                    ("timestamp","open","high","low","close","volume","amount")}
    class CurrentDayClient:
        klines=CurrentDayKlines()
    snap=build_observation(CurrentDayClient(),now_utc=current,
            repo_sha="d"*40,sequence=5)
    cache=tmp_path/"cache.json"
    atomic_publish(str(cache),snap)
    result=read_cn_tickflow_research_data(
        "159611.SZ","15m",path=str(cache),now_utc=current,
        research_mode="session_progress")
    assert result["ok"] is True
    assert result["status"]=="PASS_RESEARCH_ONLY"
    assert result["expected_grid_progress"]=="DUE_LABEL_PRESENT_NOT_FINALITY_PROOF"
    assert result["bar_finality"]=="NOT_VERIFIED"
    assert result["currentness"]=="UNPROVEN"
    assert result["radar_admission"]=="BLOCKED"
    assert result["live_trade"] is False

def test_offsession_cache_refresh_interval_is_explicit_historical_only(tmp_path):
    current=datetime(2026,10,11,7,16,tzinfo=timezone.utc)
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
    assert hist["max_age_seconds"]==1080
    too_late=read_cn_tickflow_research_data("159611.SZ",
        path=str(p),now_utc=current+timedelta(seconds=1090),
        research_mode="historical_only")
    assert too_late["status"]=="STALE"

def test_postclose_session_progress_uses_bounded_research_age(tmp_path):
    current=datetime(2026,10,14,7,5,tzinfo=timezone.utc)  # Shanghai 15:05
    class CurrentDayKlines:
        def get(self,symbol,*,period,count,as_dataframe,adjust):
            df=frame(period,"2026-10-14")
            return {key:df[key].tolist() for key in
                    ("timestamp","open","high","low","close","volume","amount")}
    class CurrentDayClient:
        klines=CurrentDayKlines()
    snap=build_observation(CurrentDayClient(),now_utc=current,
            repo_sha="a"*40,sequence=2)
    p=tmp_path/"obs.json"
    atomic_publish(str(p),snap)
    later=current+timedelta(seconds=300)
    result=read_cn_tickflow_research_data("159611.SZ","15m",path=str(p),
            now_utc=later)
    assert result["ok"] is True
    assert result["status"]=="PASS_RESEARCH_ONLY"
    assert result["max_age_seconds"]==360
    assert result["currentness"]=="UNPROVEN"
    assert result["radar_admission"]=="BLOCKED"

def test_unrecognized_research_mode_cannot_disable_gates(tmp_path):
    q=read_cn_tickflow_research_data("159611.SZ",
            path=str(tmp_path/"fake"),research_mode="production")
    assert q["status"]=="INVALID_REQUEST"
    assert q["radar_admission"]=="BLOCKED"
    assert q["live_trade"] is False

def test_current_day_vendor_bar_quarantine_cause_is_bounded_counter():
    current=datetime(2026,10,13,5,38,tzinfo=timezone.utc)
    baseline=frame("15m","2026-10-09").iloc[:6].copy()
    current_frame=frame("15m","2026-10-13").iloc[8:10].copy()
    current_frame.loc[current_frame.index[0],"high"]=0
    current_frame.loc[current_frame.index[1],"volume"]=-1
    merged=pd.concat([baseline,current_frame],ignore_index=True)
    raw={k:merged[k].tolist() for k in ("timestamp","open","high",
                                      "low","close","volume","amount")}
    counts={}
    bars=normalize_bars(raw,"15m",now_utc=current,quarantine_counts=counts)
    assert len(bars)==6
    assert counts=={"TODAY_NONPOSITIVE_OHLC":1,"TODAY_NEGATIVE_VOLUME":1}
    assert not any("secret" in str(k) for k in counts)

def test_previous_day_invalid_ohlc_still_aborts_with_metrics_enabled():
    current=datetime(2026,10,13,5,18,tzinfo=timezone.utc)
    earlier=frame("15m","2026-10-09")
    earlier.loc[earlier.index[0],"high"]=0
    raw={k:earlier[k].tolist() for k in ("timestamp","open","high",
                                          "low","close","volume","amount")}
    counts={}
    with pytest.raises(ValueError):
        normalize_bars(raw,"15m",now_utc=current,quarantine_counts=counts)
    assert not counts

def test_ohlc_gap_evidence_is_bounded_magnitude_not_raw_prices():
    from datetime import datetime, timezone
    now=datetime(2026,10,13,5,38,tzinfo=timezone.utc)
    old=frame("15m","2026-10-09").iloc[:6].copy()
    t=frame("15m","2026-10-13").iloc[8:10].copy()
    # One near-boundary high discrepancy; another inverted high/low
    # where swapping would enclose the body; neither is auto-corrected.
    t.loc[t.index[0],["high","low"]]=[1.59999,1.3]
    t.loc[t.index[1],["high","low"]]=[1.40,1.70]
    merged=pd.concat([old,t],ignore_index=True)
    raw={k:merged[k].tolist() for k in ("timestamp","open","high",
             "low","close","volume","amount")}
    quarantined={}
    evidence={}
    bars=normalize_bars(raw,"15m",now_utc=now,
         quarantine_counts=quarantined,quarantine_evidence=evidence)
    assert len(bars)==len(old)+1
    assert bars[-1]["ohlc_validation"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    assert bars[-1]["high"]==1.59999  # exact native float, not repaired
    assert sum(quarantined.values())==1
    assert evidence.get("GAP_LT_1BP",0)==0  # near-boundary row is retained
    assert evidence["GAP_GE_100BP"]==1
    assert evidence["HILO_SWAP_WOULD_ENCLOSE_BODY"]==1
    assert all("price" not in k.lower() for k in evidence)
    assert all(type(v) is int and v>=1 for v in evidence.values())


def test_historical_invalid_ohlc_cannot_be_waived_by_diagnostic():
    now=datetime(2026,10,13,5,38,tzinfo=timezone.utc)
    old=frame("15m","2026-10-09")
    old.loc[old.index[0],"high"]=0.1
    raw={k:old[k].tolist() for k in ("timestamp","open","high",
             "low","close","volume","amount")}
    evidence={}
    with pytest.raises(ValueError):
        normalize_bars(raw,"15m",now_utc=now,quarantine_evidence=evidence)
    assert evidence=={}

def test_today_ohlc_tick_lattice_shadow_can_identify_rounding_only():
    now=datetime(2026,10,13,5,38,tzinfo=timezone.utc)
    before=frame("15m","2026-10-09").iloc[:6].copy()
    today=frame("15m","2026-10-13").iloc[8:10].copy()
    today.loc[today.index[0],["open","high","low","close"]]=[
        1.5,1.59999999,1.3,1.6]
    today.loc[today.index[1],["open","high","low","close"]]=[
        1.5,1.4,1.3,1.6]
    df=pd.concat([before,today],ignore_index=True)
    raw={k:df[k].tolist() for k in
         ("timestamp","open","high","low","close","volume","amount")}
    reasons={}
    evidence={}
    out=normalize_bars(raw,"15m",now_utc=now,
         quarantine_counts=reasons,quarantine_evidence=evidence)
    # The tiny tick-lattice-compatible vendor float row is retained
    # unchanged for blocked RESEARCH ONLY. The genuinely invalid second
    # row stays quarantined, and must not be auto-repaired.
    assert len(out)==7
    assert out[-1]["ohlc_validation"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    assert out[-1]["high"]==1.59999999
    assert evidence["ETF_TICK_LATTICE_NEAR"]==1
    assert evidence.get("ETF_LATTICE_QUANTIZE_WOULD_ENCLOSE_BODY",0)==0
    assert evidence.get("ETF_TICK_LATTICE_FAR",0)==0

def test_today_ohlc_off_tick_grid_never_counted_as_repairable():
    now=datetime(2026,10,13,5,38,tzinfo=timezone.utc)
    before=frame("15m","2026-10-09").iloc[:6].copy()
    today=frame("15m","2026-10-13").iloc[8:9].copy()
    today.loc[today.index[0],["open","high","low","close"]]=[
         1.5,1.5994,1.3,1.6]
    df=pd.concat([before,today],ignore_index=True)
    raw={k:df[k].tolist() for k in
         ("timestamp","open","high","low","close","volume","amount")}
    evidence={}
    out=normalize_bars(raw,"15m",now_utc=now,quarantine_evidence=evidence)
    assert len(out)==6
    assert evidence["ETF_TICK_LATTICE_FAR"]==1
    assert evidence.get("ETF_LATTICE_QUANTIZE_WOULD_ENCLOSE_BODY",0)==0



def test_post_close_tiny_vendor_float_gap_keeps_native_bar_for_historical_research(tmp_path):
    """Same-day TickFlow floats may be observed only after close, without fixing price."""
    now=datetime(2026,10,14,7,5,tzinfo=timezone.utc)  # Shanghai 15:05
    prior=frame("15m","2026-10-13").iloc[:8].copy()
    today=frame("15m","2026-10-14").copy()
    # Original TickFlow float JSON can represent 1.600 as 1.599999999999999.
    today["high"]=1.5999999999999994
    mixed=pd.concat([prior,today],ignore_index=True)
    raw={k:mixed[k].tolist() for k in
         ("timestamp","open","high","low","close","volume","amount")}
    quarantined={}
    output=normalize_bars(raw,"15m",now_utc=now,quarantine_counts=quarantined)
    assert len(output)==len(mixed)
    assert output[-1]["label"]=="2026-10-14 15:00"
    assert output[-1]["high"]==1.5999999999999994
    assert output[-1]["ohlc_validation"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    assert output[-1]["bar_finality"]=="NOT_VERIFIED"
    assert output[-1]["is_partial_bar"] is True
    assert not quarantined

    class Klines:
        def get(self,symbol,*,period,count,as_dataframe,adjust):
            if period=="15m":
                return raw
            p=frame(period,"2026-10-14")
            return {k:p[k].tolist() for k in
                    ("timestamp","open","high","low","close","volume","amount")}
    class Client:
        klines=Klines()
    snap=build_observation(Client(),now_utc=now,repo_sha="e"*40,sequence=1)
    p=tmp_path/"native-eod.json"
    atomic_publish(str(p),snap)
    hist=read_cn_tickflow_research_data("159611.SZ","15m",
         limit=1,path=str(p),now_utc=now,research_mode="historical_only")
    assert hist["status"]=="PASS_HISTORICAL_ONLY" and hist["ok"] is True
    assert hist["rows"][-1]["high"]==1.5999999999999994
    assert hist["rows"][-1]["ohlc_validation"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    assert hist["bar_finality"]=="NOT_VERIFIED"
    assert hist["currentness"]=="UNPROVEN"
    assert hist["can_confirm_signal"] is False
    assert hist["radar_admission"]=="BLOCKED"
    assert hist["source_arbiter_admission"]=="BLOCKED"
    assert hist["live_trade"] is False
    strict=read_cn_tickflow_research_data("159611.SZ","15m",
         limit=1,path=str(p),now_utc=now,research_mode="session_progress")
    assert strict["ok"] is True and strict["status"]=="PASS_RESEARCH_ONLY"


def test_intraday_vendor_float_precision_research_only_remains_unclosed():
    now=datetime(2026,10,14,5,37,tzinfo=timezone.utc)  # Shanghai 13:37
    prior=frame("15m","2026-10-13").iloc[:8].copy()
    current=frame("15m","2026-10-14").iloc[8:10].copy()
    current["high"]=1.5999999999999994
    mixed=pd.concat([prior,current],ignore_index=True)
    raw={k:mixed[k].tolist() for k in
         ("timestamp","open","high","low","close","volume","amount")}
    reasons={}
    got=normalize_bars(raw,"15m",now_utc=now,quarantine_counts=reasons)
    assert len(got)==len(prior)+2
    assert reasons=={}
    assert all(item["bar_finality"]=="NOT_VERIFIED" for item in got)
    assert all(item["is_partial_bar"] is True for item in got)
    assert all(item["ohlc_validation"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
               for item in got[-2:])
    # No raw OHLC rewriting: same native floats stay research-only.
    assert all(item["high"]==1.5999999999999994 for item in got[-2:])


def test_postclose_large_gap_and_non_tick_lattice_stay_quarantined():
    now=datetime(2026,10,14,7,5,tzinfo=timezone.utc)
    old=frame("15m","2026-10-13").iloc[:8].copy()
    today=frame("15m","2026-10-14").iloc[14:16].copy()
    today.loc[today.index[0],"high"]=1.598  # 0.002 true shape violation
    today.loc[today.index[1],"high"]=1.599995  # tiny gap but not <=1e-5 from tick?
    # second is within 1e-5 from 1.600 and valid by vendor's precision
    # contract; use off-grid 1.59949 to ensure it remains excluded.
    today.loc[today.index[1],"high"]=1.59949
    merged=pd.concat([old,today],ignore_index=True)
    raw={k:merged[k].tolist() for k in
         ("timestamp","open","high","low","close","volume","amount")}
    reasons={}
    got=normalize_bars(raw,"15m",now_utc=now,quarantine_counts=reasons)
    assert len(got)==len(old)
    assert reasons["TODAY_HIGH_BELOW_BODY"]==2


def test_tiny_vendor_intraday_precision_exception_never_grants_trade_or_finality(tmp_path):
    # Reproduce only the 2026-10-15 159611 10:00 vendor float-shape
    # category on synthesized data, not any actual provider price.
    now=datetime(2026,10,15,2,2,tzinfo=timezone.utc)  # Shanghai 10:02
    prior=frame("15m","2026-10-14").iloc[:8].copy()
    today=frame("15m","2026-10-15").iloc[:2].copy()
    today["high"]=1.5999999999999994  # native vendor float, <1e-5 above-body gap
    mixed=pd.concat([prior,today],ignore_index=True)
    raw={k:mixed[k].tolist() for k in
         ("timestamp","open","high","low","close","volume","amount")}

    rows=normalize_bars(raw,"15m",now_utc=now)
    assert len(rows)==len(mixed)
    assert [row["label"][-5:] for row in rows[-2:]]==["09:45","10:00"]
    assert all(row["ohlc_validation"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
               for row in rows[-2:])
    assert all(row["high"]==1.5999999999999994 for row in rows[-2:])
    assert all(row["bar_finality"]=="NOT_VERIFIED"
               and row["is_partial_bar"] is True for row in rows)

    class Klines:
        def get(self,symbol,*,period,count,as_dataframe,adjust):
            if symbol=="159611.SZ" and period=="15m":
                return raw
            df=frame(period,"2026-10-14")
            return {k:df[k].tolist() for k in
                    ("timestamp","open","high","low","close","volume","amount")}
    class Client:
        klines=Klines()
    snap=build_observation(Client(),now_utc=now,repo_sha="a"*40,sequence=17)
    path=tmp_path/"research-precision.json"
    atomic_publish(str(path),snap)
    accepted=read_cn_tickflow_research_data(
        "159611.SZ","15m",limit=2,path=str(path),now_utc=now,
        research_mode="session_progress",
    )
    assert accepted["status"]=="PASS_RESEARCH_ONLY"
    assert accepted["ok"] is True
    assert accepted["ohlc_precision_scope"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    assert accepted["tolerated_vendor_float_rows"]==2
    assert accepted["bar_finality"]=="NOT_VERIFIED"
    assert accepted["exchange_bar_finality"]=="NOT_VERIFIED"
    assert accepted["currentness"]=="UNPROVEN"
    assert accepted["can_confirm_signal"] is False
    assert accepted["radar_admission"]=="BLOCKED"
    assert accepted["source_arbiter_admission"]=="BLOCKED"
    assert accepted["live_trade"] is False
    assert accepted["canonical_write_authorized"] is False


def test_vendor_precision_intraday_waits_90_seconds_and_never_excuses_true_shape_error():
    prior=frame("15m","2026-10-14").iloc[:8].copy()
    current=frame("15m","2026-10-15").iloc[:2].copy()
    current["high"]=1.5999999999999994
    merged=pd.concat([prior,current],ignore_index=True)
    raw={k:merged[k].tolist() for k in
         ("timestamp","open","high","low","close","volume","amount")}
    # At 10:00:30 the 10:00 bar is still within publish grace.
    near=datetime(2026,10,15,2,0,30,tzinfo=timezone.utc)
    reasons={}
    rows=normalize_bars(raw,"15m",now_utc=near,quarantine_counts=reasons)
    assert [item["label"] for item in rows if item["label"].startswith("2026-10-15")]==[
        "2026-10-15 09:45"
    ]
    assert reasons.get("TODAY_HIGH_BELOW_BODY")==1

    current.loc[current.index[1],"high"]=1.598  # genuine invalid 0.002 CNY gap
    changed=pd.concat([prior,current],ignore_index=True)
    raw={k:changed[k].tolist() for k in
         ("timestamp","open","high","low","close","volume","amount")}
    rows=normalize_bars(raw,"15m",
                        now_utc=datetime(2026,10,15,2,2,tzinfo=timezone.utc))
    assert all(item["label"]!="2026-10-15 10:00" for item in rows)
    assert all(item["bar_finality"]=="NOT_VERIFIED" for item in rows)


def test_session_progress_rejects_middle_due_gap_even_when_last_bar_present(tmp_path):
    """Real 159611 scenario: a skipped 10:00 must block at 10:17, even limit=1."""
    now = datetime(2026, 10, 15, 2, 17, tzinfo=timezone.utc)  # 10:17 Shanghai
    snap = build_observation(FakeClient(), now_utc=now, repo_sha="e"*40, sequence=7)
    today_rows = snap["symbols"]["159611.SZ"]["15m"]["rows"]
    template = dict(today_rows[-1])
    today_rows.extend([
        {**template, "label": "2026-10-15 09:45"},
        {**template, "label": "2026-10-15 10:15"},
    ])
    cache = tmp_path / "gap.json"
    atomic_publish(str(cache), snap)
    blocked = read_cn_tickflow_research_data(
        "159611.SZ", "15m", 1, path=str(cache), now_utc=now,
        research_mode="session_progress",
    )
    assert blocked["ok"] is False
    assert blocked["status"] == "BAR_LABEL_BEHIND_SESSION"
    assert blocked["due_grid_continuity"] == "INCOMPLETE"
    assert blocked["rows"] == []
    assert blocked["radar_admission"] == "BLOCKED"
    historical = read_cn_tickflow_research_data(
        "159611.SZ", "15m", 1, path=str(cache), now_utc=now,
        research_mode="historical_only",
    )
    assert historical["ok"] is True
    assert historical["status"] == "PASS_HISTORICAL_ONLY"
    assert historical["expected_grid_progress"] == (
        "DUE_LABEL_PRESENT_WITH_GAPS_HISTORICAL_ONLY"
    )
    today_rows.insert(-1, {**template, "label": "2026-10-15 10:00"})
    atomic_publish(str(cache), snap)
    complete = read_cn_tickflow_research_data(
        "159611.SZ", "15m", 1, path=str(cache), now_utc=now,
        research_mode="session_progress",
    )
    assert complete["ok"] is True
    assert complete["status"] == "PASS_RESEARCH_ONLY"
    assert complete["expected_grid_progress"] == "DUE_LABEL_PRESENT_NOT_FINALITY_PROOF"
    assert complete["bar_finality"] == "NOT_VERIFIED"
    assert complete["radar_admission"] == "BLOCKED"


def test_research_reader_small_limit_does_not_hide_poisoned_earlier_row(tmp_path):
    snap = build_observation(FakeClient(), now_utc=NOW, repo_sha="e"*40, sequence=7)
    snap["symbols"]["159611.SZ"]["15m"]["rows"][0]["high"] = -1
    cache = tmp_path / "poisoned.json"
    atomic_publish(str(cache), snap)
    observed = read_cn_tickflow_research_data(
        "159611.SZ", "15m", 1, path=str(cache), now_utc=NOW,
        research_mode="historical_only",
    )
    assert observed["status"] == "INVALID_CACHE"
    assert observed["ok"] is False


def test_historical_cache_rejection_exposes_only_fixed_safe_reason(tmp_path):
    snap = build_observation(FakeClient(), now_utc=NOW, repo_sha="e"*40, sequence=8)
    snap["symbols"]["159611.SZ"]["15m"]["rows"][0]["high"] = -1
    cache = tmp_path / "invalid-shape.json"
    atomic_publish(str(cache), snap)
    result = read_cn_tickflow_research_data(
        "159611.SZ", "15m", 1, path=str(cache), now_utc=NOW,
        research_mode="historical_only",
    )
    assert result["status"] == "INVALID_CACHE"
    assert result["cache_rejection_reason"] == "BAR_OHLC_INVALID"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert "1.5" not in json.dumps(result)
    assert "SECRET_SHOULD_NOT_LEAK" not in json.dumps(result)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("schema", "untrusted-schema", "CACHE_SCHEMA_MISMATCH"),
        ("provider", "untrusted-provider", "CACHE_PROVIDER_MISMATCH"),
        ("status", "untrusted-status", "CACHE_STATUS_MISMATCH"),
    ],
)
def test_cache_envelope_rejection_is_specific_bounded_and_fail_closed(
    tmp_path, field, value, reason,
):
    snap = build_observation(FakeClient(), now_utc=NOW, repo_sha="e"*40, sequence=8)
    snap[field] = value
    cache = tmp_path / "invalid-envelope.json"
    atomic_publish(str(cache), snap)
    result = read_cn_tickflow_research_data(
        "159611.SZ", "15m", 1, path=str(cache), now_utc=NOW,
        research_mode="historical_only",
    )
    assert result["status"] == "INVALID_CACHE"
    assert result["cache_rejection_reason"] == reason
    assert value not in json.dumps(result)
    assert result["provider_requests"] == 0
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_batch_failure_has_bounded_stage_and_reason_before_symbol_normalization():
    from scripts.run_cn_tickflow_research_worker import _normalize_rejection_reason

    fake = FakeClient()
    fake.klines.intraday_batch = lambda *args, **kwargs: []
    with pytest.raises(ValueError) as caught:
        build_observation(fake, now_utc=NOW, repo_sha="a"*40, sequence=1,
                          include_supplemental=True, use_batch=True)
    assert getattr(caught.value, "_tickflow_stage", None) == "BATCH_1M_FETCH"
    assert _normalize_rejection_reason(caught.value) == "BATCH_SHAPE_INVALID"


def test_batch_missing_symbol_count_over_fallback_cap_fails_closed():
    from scripts.run_cn_tickflow_research_worker import _normalize_rejection_reason

    fake = FakeClient()
    symbols = tuple(f"00000{index}.SZ" for index in range(1, 7))
    fake.klines.intraday_batch = lambda requested, **kwargs: {
        requested[0]: fake.klines.get(
            requested[0], period=kwargs["period"], count=kwargs["count"],
            as_dataframe=kwargs["as_dataframe"], adjust="none",
        )
    }
    with pytest.raises(ValueError) as caught:
        build_observation(fake, now_utc=NOW, repo_sha="a"*40, sequence=1,
                          symbols=symbols,allow_scan_symbols=True,
                          include_supplemental=True,use_batch=True)
    assert getattr(caught.value,"_tickflow_stage",None)=="BATCH_1M_FETCH"
    assert _normalize_rejection_reason(caught.value)=="BATCH_SYMBOL_MISSING"


def test_normalizer_splits_below_minimum_and_above_bound_row_counts():
    base=frame("60m")
    columns=("timestamp","open","high","low","close","volume","amount")
    too_few={key:base[key].tolist()[:3] for key in columns}
    too_many={key:(base[key].tolist()*7)[:25] for key in columns}
    with pytest.raises(ValueError,match="insufficient history"):
        normalize_bars(too_few,"60m",now_utc=NOW)
    with pytest.raises(ValueError,match="history exceeds configured bound"):
        normalize_bars(too_many,"60m",now_utc=NOW)
