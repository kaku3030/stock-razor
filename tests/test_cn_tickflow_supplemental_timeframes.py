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


def test_5m_and_d1_are_optin_without_breaking_existing_4_calls(tmp_path):
    client=Client()
    old=build_observation(client,now_utc=POSTCLOSE,repo_sha=SHA,sequence=1)
    assert len(client.klines.calls)==4
    assert all(set(frames)=={"15m","60m"} for frames in old["symbols"].values())
    client.klines.calls.clear()
    got=build_observation(client,now_utc=POSTCLOSE,repo_sha=SHA,sequence=2,
                          include_supplemental=True)
    assert len(client.klines.calls)==8
    assert [x[1:3] for x in client.klines.calls[:4]] == [
        ("15m",96),("60m",24),("5m",144),("1d",40)]
    assert all(x[3:]==("none",False) for x in client.klines.calls)
    p=tmp_path/"cache.json"
    atomic_publish(str(p),got)
    assert p.stat().st_size<MAX_BYTES
    for symbol in ("159611.SZ","518880.SH"):
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
