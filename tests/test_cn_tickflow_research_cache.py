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
        self.intraday_calls=[]
        self.batch_calls=[]
        self.intraday_batch_calls=[]
        self.window_calls=[]
    def get(self,symbol,*,period,count,as_dataframe,adjust,start_time=None,end_time=None):
        self.calls.append((symbol,period,count,as_dataframe,adjust))
        self.window_calls.append((symbol,period,start_time,end_time))
        df = frame(period)
        return {key: df[key].tolist() for key in
                ("timestamp","open","high","low","close","volume","amount")}

    def intraday(self,symbol,*,period,count,as_dataframe):
        self.intraday_calls.append((symbol,period,count,as_dataframe))
        df = frame(period)
        return {key: df[key].tolist() for key in
                ("timestamp","open","high","low","close","volume","amount")}

    def batch(self, symbols, **kwargs):
        self.batch_calls.append((list(symbols), kwargs))
        return {symbol: self.get(
            symbol, period=kwargs["period"], count=kwargs["count"],
            as_dataframe=kwargs["as_dataframe"], adjust=kwargs.get("adjust", "none"),
            start_time=kwargs.get("start_time"),end_time=kwargs.get("end_time"),
        ) for symbol in symbols}

    def intraday_batch(self, symbols, **kwargs):
        self.intraday_batch_calls.append((list(symbols), kwargs))
        return {symbol: self.get(
            symbol, period=kwargs["period"], count=kwargs["count"],
            as_dataframe=kwargs["as_dataframe"], adjust="none",
        ) for symbol in symbols}

    def intraday(self,symbol,*,period,count,as_dataframe):
        self.intraday_calls.append((symbol,period,count,as_dataframe))
        return self.get(symbol,period=period,count=count,
                        as_dataframe=as_dataframe,adjust="none")

class FakeClient:
    def __init__(self):
        self.klines=FakeKlines()

def _compact_multi_day(period, days, *, close=1.6):
    rows=[]
    clocks=("00:00",) if period=="1d" else TIMES[period]
    for day in days:
        for clock in clocks:
            stamp=datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=SH)
            rows.append({
                "timestamp":int(stamp.timestamp()*1000),"open":1.5,
                "high":1.7,"low":1.3,"close":close,"volume":1000,
                "amount":close*1000,
            })
    return {key:[row[key] for row in rows]
            for key in ("timestamp","open","high","low","close","volume","amount")}


def test_historical_warmup_uses_explicit_windows_and_intraday_overrides():
    from datetime import date, timedelta as dt_timedelta
    from data_provider.cn_tickflow_research_cache import _HISTORY_WARMUP_ROWS

    now=datetime(2026,10,13,7,5,tzinfo=timezone.utc)  # 15:05 Shanghai
    days=("2026-10-05","2026-10-06","2026-10-07",
          "2026-10-08","2026-10-09","2026-10-13")
    daily_days=[]
    cursor=date(2026,10,12)
    while len(daily_days)<60:
        if cursor.weekday()<5:
            daily_days.append(cursor.isoformat())
        cursor-=dt_timedelta(days=1)
    daily_days.reverse()

    class HistoryKlines(FakeKlines):
        def batch(self,symbols,**kwargs):
            self.batch_calls.append((list(symbols),kwargs))
            period=kwargs["period"]
            if period in ("15m","60m"):
                return {symbol:_compact_multi_day(period,days)
                        for symbol in symbols}
            if period=="1d":
                return {symbol:_compact_multi_day("1d",daily_days)
                        for symbol in symbols}
            return super().batch(symbols,**kwargs)

        def intraday_batch(self,symbols,**kwargs):
            self.intraday_batch_calls.append((list(symbols),kwargs))
            period=kwargs["period"]
            if period in ("15m","60m"):
                return {symbol:_compact_multi_day(
                    period,("2026-10-13",),close=1.65)
                    for symbol in symbols}
            return super().intraday_batch(symbols,**kwargs)

    fake=FakeClient()
    fake.klines=HistoryKlines()
    snap=build_observation(
        fake,now_utc=now,repo_sha="a"*40,sequence=1,
        symbols=("159611.SZ",),include_supplemental=True,use_batch=True,
    )
    assert len(fake.klines.batch_calls)==3
    historical={kwargs["period"]:kwargs
                for _,kwargs in fake.klines.batch_calls}
    end_ms=int(now.timestamp()*1000)
    assert set(historical)=={"15m","60m","1d"}
    for period,kwargs in historical.items():
        assert kwargs["end_time"]==end_ms
        days_back=14 if period in ("15m","60m") else 120
        assert kwargs["start_time"]==end_ms-days_back*24*60*60*1000
        assert kwargs["count"]==_HISTORY_WARMUP_ROWS[period]
    symbol=snap["symbols"]["159611.SZ"]
    for period in ("15m","60m","1d"):
        coverage=symbol[period]["history_coverage"]
        assert coverage=={
            "required_rows":_HISTORY_WARMUP_ROWS[period],
            "observed_rows":_HISTORY_WARMUP_ROWS[period],"status":"PASS",
        }
    assert len(symbol["15m"]["rows"])==96
    assert len(symbol["60m"]["rows"])==24
    assert len(symbol["1d"]["rows"])==60
    assert symbol["15m"]["rows"][-1]["close"]==1.65
    assert symbol["60m"]["rows"][-1]["close"]==1.65
    assert snap["radar_admission"]=="BLOCKED"
    assert snap["live_trade"] is False


def test_short_historical_response_is_explicitly_marked_below_warmup_minimum():
    now=datetime(2026,10,13,7,5,tzinfo=timezone.utc)
    class ShortHistory(FakeKlines):
        def batch(self,symbols,**kwargs):
            self.batch_calls.append((list(symbols),kwargs))
            return {symbol:frame(kwargs["period"],"2026-10-12").to_dict(orient="list")
                    for symbol in symbols}
        def intraday_batch(self,symbols,**kwargs):
            self.intraday_batch_calls.append((list(symbols),kwargs))
            return {symbol:frame(kwargs["period"],"2026-10-12").to_dict(orient="list")
                    for symbol in symbols}
    fake=FakeClient(); fake.klines=ShortHistory()
    snap=build_observation(
        fake,now_utc=now,repo_sha="b"*40,sequence=1,
        symbols=("159611.SZ",),use_batch=True,
    )
    coverage=snap["symbols"]["159611.SZ"]["15m"]["history_coverage"]
    assert coverage["status"]=="ROW_COUNT_BELOW_MIN"
    assert coverage["required_rows