"""TickFlow cloud 5m and D1 research cache, bounded and fail closed."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data_provider.cn_tickflow_research_cache import (
    CN, MAX_BYTES, _LABEL_END, _expected_closed_grid_label,
    build_observation, atomic_publish, read_cn_tickflow_research_data,
)

SHA="b"*40
POSTCLOSE=datetime(2026,10,14,7,10,tzinfo=timezone.utc)


def _minutes(period, day):
    if period=="1d":
        dates=("2026-10-07","2026-10-08","2026-10-09",
               "2026-10-12","2026-10-13",day)
        return [datetime.fromisoformat(d+"T00:00:00").replace(tzinfo=CN)
                for d in dates]
    return [datetime.fromisoformat(day+"T"+clock+":00").replace(tzinfo=CN)
            for clock in sorted(_LABEL_END[period])]


class KlineGetter:
    def __init__(self):
        self.calls=[]
    def get(self,symbol,*,period,count,adjust,as_dataframe):
        self.calls.append((symbol,period,count,adjust,as_dataframe))
        times=_minutes(period,"2026-10-14")
        if period=="5m":
            times=_minutes(period,"2026-10-13")+times
        return {"timestamp":[int(t.timestamp())*1000 for t in times],
                "open":[1.500 for t in times],
                "high":[1.510 for t in times],
                "low":[1.490 for t in times],
                "close":[1.505 for t in times],
                "volume":[2000 for t in times],
                "amount":[3000 for t in times]}


class Client:
    def __init__(self):
        self.klines=KlineGetter()


def test_5m_day_grid_is_exact_regular_session_48():
    assert len(_LABEL_END["5m"])==48
    assert {"09:35","11:30","13:05","15:00"}.issubset(_LABEL_END["5m"])
    assert not {"09:30","11:35","13:00","15:05"} & _LABEL_END["5m"]


def test_all_held_etfs_and_five_periods_are_requested_in_one_snapshot(tmp_path):
    client=Client()
    old=build_observation(client,now_utc=POSTCLOSE,repo_sha=SHA,sequence=1)
    assert len(client.klines.calls)==10
    assert all(set(frames)=={"15m","60m"} for frames in old["symbols"].values())
    client.klines.calls.clear()
    got=build_observation(client,now_utc=POSTCLOSE,repo_sha=SHA,sequence=2,
                          include_supplemental=True)
    assert len(client.klines.calls)==25
    assert [x[1:3] for x in client.klines.calls[:5]] == [
        ("1m",240),("5m",144),("15m",96),("60m",24),("1d",40)]
    assert all(x[3:]==("none",False) for x in client.klines.calls)
    p=tmp_path/"cache.json"
    atomic_publish(str(p),got)
    assert p.stat().st_size<MAX_BYTES
    for symbol in ("159611.SZ","159209.SZ","518880.SH","512730.SH","159363.SZ"):
        for period,n in (("5m",48),("1d",6)):
            resp=read_cn_tickflow_research_data(
                symbol,period,limit=144,path=str(p),now_utc=POSTCLOSE,
                research_mode="historical_only")
            assert resp["status"]=="PASS_HISTORICAL_ONLY"
            assert resp["ok"] is True
            assert len(resp["rows"])==n if period=="1d" else len(resp["rows"])==96
            assert resp["radar_admission"]=="BLOCKED"
            assert resp["bar_finality"]=="NOT_VERIFIED"
            assert resp["live_trade"] is False
            assert resp["provider_requests"]==0
            assert resp["rows"][-1]["label"].startswith("2026-10-14")
    # Date-labelled daily bar must NEVER be allowed as session-progress evidence.
    rejected=read_cn_tickflow_research_data(
        "159611.SZ","1d",path=str(p),now_utc=POSTCLOSE,
        research_mode="session_progress")
    assert rejected["status"]=="INVALID_REQUEST"
    assert rejected["ok"] is False


def test_snapshot_bounds_provider_rows_to_requested_count():
    class OverReturningGetter(KlineGetter):
        def get(self,symbol,*,period,count,adjust,as_dataframe):
            frame=super().get(symbol,period=period,count=count,
                              adjust=adjust,as_dataframe=as_dataframe)
            extra=([datetime.fromisoformat("2026-10-06T00:00:00").replace(tzinfo=CN)]
                   if period=="1d" else _minutes(period,"2026-10-06"))
            frame["timestamp"]=[int(t.timestamp())*1000 for t in extra]+frame["timestamp"]
            for key in ("open","high","low","close","volume","amount"):
                frame[key]=frame[key][:len(extra)]+frame[key]
            return frame

    class OverReturningClient:
        def __init__(self):
            self.klines=OverReturningGetter()

    snapshot=build_observation(OverReturningClient(),now_utc=POSTCLOSE,
                               repo_sha=SHA,sequence=3,
                               include_supplemental=True)
    assert all(len(snapshot["symbols"][symbol][period]["rows"])<=count
               for symbol in snapshot["symbols"]
               for period,count in (("1m",240),("5m",144),("15m",96),
                                    ("60m",24),("1d",40)))


def test_today_daily_date_stamp_quarantined_before_close_not_provider_finality():
    from data_provider.cn_tickflow_research_cache import normalize_bars
    client=Client()
    raw=client.klines.get("159611.SZ",period="1d",count=40,
                         as_dataframe=False,adjust="none")
    before=datetime(2026,10,14,6,0,tzinfo=timezone.utc)
    counts={}
    hist=normalize_bars(raw,"1d",now_utc=before,quarantine_counts=counts)
    assert len(hist)==5
    assert counts["TODAY_DAILY_NOT_POSTCLOSE"]==1
    after=normalize_bars(raw,"1d",now_utc=POSTCLOSE)
    assert len(after)==6
    assert after[-1]["bar_finality"]=="NOT_VERIFIED"


def test_daily_last_due_grid_not_marked_due_before_post_close():
    before=datetime(2026,10,14,6,55,tzinfo=timezone.utc)
    assert _expected_closed_grid_label(before,"1d") is None
    due=_expected_closed_grid_label(POSTCLOSE,"1d")
    assert due is not None
    assert due.strftime("%Y-%m-%d %H:%M")=="2026-10-14 00:00"


def test_intraday_5m_native_tick_precision_retained_without_trade_promotion(tmp_path):
    """Real desktop 5m counterexample: 18/24 due bars with <=1e-5 drift.

    Only non-mutating ETF tick-lattice-compatible elapsed labels qualify for
    *research*. No vendor repair, exchange finality, currentness or trading.
    """
    now=datetime(2026,10,15,3,35,tzinfo=timezone.utc) # 11:35 Shanghai
    due=sorted(t for t in _minutes("5m","2026-10-15")
               if t.strftime("%H:%M") <= "11:30")
    assert len(due)==24
    prior=_minutes("5m","2026-10-14")
    times=prior+due

    class Klines:
        def get(self,symbol,*,period,count,adjust,as_dataframe):
            if period!="5m":
                return KlineGetter().get(symbol,period=period,count=count,
                                         adjust=adjust,as_dataframe=as_dataframe)
            n=len(times)
            high=[1.510]*len(prior)+[1.504999999999]*18+[1.510]*6
            return {
                "timestamp":[int(t.timestamp())*1000 for t in times],
                "open":[1.500]*n,"high":high,"low":[1.490]*n,
                "close":[1.505]*n,"volume":[2000]*n,"amount":[3000]*n,
            }

    class MixedClient:
        klines=Klines()

    snap=build_observation(MixedClient(),now_utc=now,repo_sha=SHA,
                           sequence=9,include_supplemental=True)
    cache=tmp_path/"native-five-minute.json"
    atomic_publish(str(cache),snap)
    progress=read_cn_tickflow_research_data(
        "159611.SZ","5m",limit=24,path=str(cache),now_utc=now,
        research_mode="session_progress")
    assert progress["ok"] is True
    assert progress["status"]=="PASS_RESEARCH_ONLY"
    assert progress["expected_grid_progress"]=="DUE_LABEL_PRESENT_NOT_FINALITY_PROOF"
    assert progress["tolerated_vendor_float_rows"]==18
    assert progress["ohlc_precision_scope"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    assert progress["rows"][-1]["label"]=="2026-10-15 11:30"
    assert progress["rows"][0]["high"]==1.504999999999
    assert all(r["is_partial_bar"] is True
               and r["bar_finality"]=="NOT_VERIFIED" for r in progress["rows"])
    assert progress["currentness"]=="UNPROVEN"
    assert progress["can_confirm_signal"] is False
    assert progress["source_arbiter_admission"]=="BLOCKED"
    assert progress["radar_admission"]=="BLOCKED"
    assert progress["live_trade"] is False
    # Historical-only intraday stays stricter: same-day tolerated bars
    # are never mislabeled closed/historical before the exchange close.
    historical=read_cn_tickflow_research_data(
        "159611.SZ","5m",limit=24,path=str(cache),now_utc=now,
        research_mode="historical_only")
    assert historical["status"]=="INVALID_CACHE"

    # Delete one due time boundary: a current last bar cannot conceal it.
    snap["symbols"]["159611.SZ"]["5m"]["rows"]=[
        row for row in snap["symbols"]["159611.SZ"]["5m"]["rows"]
        if row["label"]!="2026-10-15 10:00"
    ]
    atomic_publish(str(cache),snap)
    missing=read_cn_tickflow_research_data(
        "159611.SZ","5m",limit=1,path=str(cache),now_utc=now,
        research_mode="session_progress")
    assert missing["ok"] is False
    assert missing["status"]=="BAR_LABEL_BEHIND_SESSION"
    assert missing["due_grid_continuity"]=="INCOMPLETE"
    assert missing["rows"]==[]
    assert missing["radar_admission"]=="BLOCKED"


def test_intraday_5m_non_lattice_or_large_gap_does_not_gain_tolerance():
    from data_provider.cn_tickflow_research_cache import normalize_bars
    now=datetime(2026,10,15,3,35,tzinfo=timezone.utc)
    a=KlineGetter().get("159611.SZ",period="5m",count=144,
                       adjust="none",as_dataframe=False)
    source=_minutes("5m","2026-10-14")+[
        t for t in _minutes("5m","2026-10-15")
        if t.strftime("%H:%M")<="11:30"
    ]
    for key in a:
        if key=="timestamp":
            a[key]=[int(t.timestamp())*1000 for t in source]
        else:
            a[key]=[a[key][0]]*len(source)
    # Genuinely invalid high below 1.505 close by >1e-5 on 10:00.
    target=len(_minutes("5m","2026-10-14"))+5
    a["high"][target]=1.503
    counts={}
    result=normalize_bars(a,"5m",now_utc=now,quarantine_counts=counts)
    assert counts=={"TODAY_HIGH_BELOW_BODY":1}
    assert not any(x["label"]==source[target].strftime("%Y-%m-%d %H:%M")
                   for x in result)
    assert all(x["bar_finality"]=="NOT_VERIFIED" for x in result)
