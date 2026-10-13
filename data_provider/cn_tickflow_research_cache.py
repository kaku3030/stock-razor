"""Read-only, isolated TickFlow Premium minute observation (not canonical/trade)."""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
import re
import tempfile
from typing import Any

CN = ZoneInfo("Asia/Shanghai")
SCHEMA = "stock_razor_cn_tickflow_research_observation_v0_1"
DEFAULT_PATH = "/run/stock-razor-cn-tickflow/latest-research-observation.json"
SYMBOLS = ("159611.SZ", "518880.SH")
TIMEFRAMES = ("15m", "60m")
MAX_BYTES = 150_000
MAX_AGE_SECONDS = 180
_LABEL_END = {
    "15m": frozenset(("09:45","10:00","10:15","10:30","10:45","11:00",
       "11:15","11:30","13:15","13:30","13:45","14:00","14:15",
       "14:30","14:45","15:00")),
    "60m": frozenset(("10:30","11:30","14:00","15:00")),
}
_SYMBOL_RE = re.compile(r"^(?:[0-9]{6})\.(?:SH|SZ)$")
_ALLOWED_PERIODS = {"15m":96,"60m":24}
_SOURCE = "TICKFLOW_PREMIUM"

def _timestamp(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError("invalid provider timestamp")
    epoch = float(value)
    if epoch > 1e12:
        epoch /= 1000
    if not 1_500_000_000 <= epoch <= 2_400_000_000:
        raise ValueError("provider epoch outside bounded range")
    return datetime.fromtimestamp(epoch, timezone.utc)

def _number(row: dict, *names: str) -> float:
    for key in names:
        if key in row:
            value = row[key]
            if isinstance(value, bool) or not isinstance(value,(int,float)) or not isfinite(value):
                raise ValueError("invalid provider number")
            return float(value)
    raise ValueError("missing provider column")

def _select_timestamp(row: dict) -> datetime:
    for key in ("timestamp", "time", "datetime", "date"):
        if key in row:
            return _timestamp(row[key])
    raise ValueError("no provider timestamp")

def normalize_bars(frame: Any, timeframe: str, *, now_utc: datetime) -> list[dict]:
    """Price-bearing bars stay on AWS; no current-bar finality is asserted."""
    if timeframe not in _ALLOWED_PERIODS:
        raise ValueError("unsupported period")
    if now_utc.tzinfo is None:
        raise ValueError("naive clock")
    if not hasattr(frame, "to_dict"):
        raise ValueError("unexpected SDK data type")
    records = frame.to_dict(orient="records")
    if not isinstance(records, list) or not 4 <= len(records) <= _ALLOWED_PERIODS[timeframe]:
        raise ValueError("insufficient or unbounded history")
    bars=[]
    previous=None
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("non-dict record")
        stamp=_select_timestamp(raw)
        if previous is not None and stamp<=previous:
            raise ValueError("reordered/duplicate timestamp")
        previous=stamp
        sh=stamp.astimezone(CN)
        if sh.second != 0 or sh.microsecond or sh.strftime("%H:%M") not in _LABEL_END[timeframe]:
            raise ValueError("unexpected Shanghai regular-session grid")
        # Reject future bars, but do not pretend already elapsed means exchange-final.
        if stamp > now_utc:
            # The provider can label a still-forming 15m/60m candle by the
            # future end boundary. Drop it from research output, not all bars.
            # A future trading *date* cannot be explained by a forming bar.
            if sh.date() != now_utc.astimezone(CN).date():
                raise ValueError("future trading date")
            continue
        op=_number(raw,"open","open_price")
        hi=_number(raw,"high","high_price")
        lo=_number(raw,"low","low_price")
        cl=_number(raw,"close","close_price")
        vol=_number(raw,"volume","vol")
        amt=_number(raw,"amount","turnover")
        if op <= 0 or cl <= 0 or lo <= 0 or hi <= 0 or hi < max(op,cl,lo) or lo > min(op,cl,hi) or vol<0 or amt<0:
            raise ValueError("invalid OHLCVA")
        bars.append({
            "label": sh.strftime("%Y-%m-%d %H:%M"),
            "open":op,"high":hi,"low":lo,"close":cl,
            "volume":vol,"amount":amt,
            "is_partial_bar": True,
            "bar_finality": "NOT_VERIFIED",
        })
    if len(bars)<4:
        raise ValueError("no sufficient historical closed-time candidates")
    return bars

def build_observation(client: Any, *, now_utc: datetime, repo_sha: str, sequence: int,
                      symbols: tuple[str,...]=SYMBOLS) -> dict:
    if now_utc.tzinfo is None or not re.fullmatch("[0-9a-f]{40}",repo_sha):
        raise ValueError("invalid wall clock or source revision")
    if type(sequence) is not int or sequence < 1:
        raise ValueError("invalid monotonic sequence")
    if not symbols or len(symbols)>4 or any(not _SYMBOL_RE.fullmatch(x) for x in symbols):
        raise ValueError("unapproved symbols")
    output={}
    for symbol in symbols:
        frames={}
        for interval, n in _ALLOWED_PERIODS.items():
            # SDK's isolated Premium Kline contract was separately verified on AWS.
            frame=client.klines.get(symbol, period=interval,count=n,as_dataframe=True)
            bars=normalize_bars(frame,interval,now_utc=now_utc)
            frames[interval]={"rows":bars,
                 "timestamp_semantic":"BAR_END_GRID_MATCH_HISTORICAL_ONLY",
                 "currentness":"UNPROVEN", "closure":"NOT_VERIFIED",
                 "volume_units":"NOT_VERIFIED",
                 "adjustment":"NOT_VERIFIED","crosscheck":"NOT_VERIFIED"}
        output[symbol]=frames
    return {
        "schema":SCHEMA, "repo_sha":repo_sha, "provider":_SOURCE,
        "observed_at_utc":now_utc.astimezone(timezone.utc).isoformat(),
        "sequence":sequence, "status":"PASS_RESEARCH_ONLY",
        "symbols":output,"provider_first_target":True,
        "source_arbiter_admission":"BLOCKED","radar_admission":"BLOCKED",
        "canonical_write_authorized":False,"can_confirm_signal":False,
        "research_only":True,"live_trade":False,
    }

def atomic_publish(path: str, payload: dict) -> None:
    parent=Path(path).parent
    parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        fd,temporary=tempfile.mkstemp(prefix=".observation-",dir=parent)
        if hasattr(os, 'fchmod'):
            os.fchmod(fd,0o600)
        else:
            os.chmod(temporary,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(payload,f,allow_nan=False,separators=(",",":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)

def read_cn_tickflow_research_data(symbol: str, timeframe: str="15m", limit:int=30,
             *, path: str=DEFAULT_PATH, now_utc:datetime|None=None) -> dict:
    """Bounded local-cache research read. Never provider I/O or trade admission."""
    base={
        "ok":False,"provider":_SOURCE,"provider_first_target":True,
        "research_only":True, "bar_finality":"NOT_VERIFIED",
        "currentness":"UNPROVEN", "source_arbiter_admission":"BLOCKED",
        "radar_admission":"BLOCKED","live_trade":False,"can_confirm_signal":False,
        "canonical_write_authorized":False, "provider_requests":0,
    }
    if not isinstance(symbol,str) or not _SYMBOL_RE.fullmatch(symbol) or timeframe not in _ALLOWED_PERIODS or type(limit)!=int or not 1<=limit<=96:
        return {**base,"status":"INVALID_REQUEST"}
    try:
        with open(path,"rb") as f:
            data=f.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:
            return {**base,"status":"INVALID_CACHE"}
        obj=json.loads(data)
    except (OSError,ValueError,TypeError,UnicodeError):
        return {**base,"status":"NO_DATA"}
    if not isinstance(obj,dict) or obj.get("schema")!=SCHEMA or obj.get("provider")!=_SOURCE or obj.get("status")!="PASS_RESEARCH_ONLY":
        return {**base,"status":"INVALID_CACHE"}
    if not (obj.get("research_only") is True and obj.get("radar_admission")=="BLOCKED" and obj.get("source_arbiter_admission")=="BLOCKED" and obj.get("live_trade") is False and obj.get("canonical_write_authorized") is False and obj.get("can_confirm_signal") is False):
        return {**base,"status":"INVALID_CACHE"}
    sha=obj.get("repo_sha")
    if not isinstance(sha,str) or not re.fullmatch("[0-9a-f]{40}",sha):
        return {**base,"status":"INVALID_CACHE"}
    try:
        now=now_utc or datetime.now(timezone.utc)
        observed=datetime.fromisoformat(obj["observed_at_utc"])
        if now.tzinfo is None or observed.tzinfo is None:
            raise ValueError
        age=(now-observed).total_seconds()
    except (ValueError,TypeError,KeyError,OverflowError):
        return {**base,"status":"INVALID_CACHE"}
    if age < -5 or age > MAX_AGE_SECONDS:
        return {**base,"status":"STALE","age_seconds":round(age,2)}
    try:
        raw=obj["symbols"][symbol][timeframe]
        rows=raw["rows"]
        if not isinstance(rows,list) or not 4<=len(rows)<=_ALLOWED_PERIODS[timeframe]:
            raise ValueError
        if raw.get("closure")!="NOT_VERIFIED" or raw.get("currentness")!="UNPROVEN":
            raise ValueError
        safe=[]
        previous=None
        for item in rows[-limit:]:
            if not isinstance(item,dict) or item.get("bar_finality")!="NOT_VERIFIED" or item.get("is_partial_bar") is not True:
                raise ValueError
            label=item.get("label")
            if not isinstance(label,str):
                raise ValueError
            bar_stamp=datetime.strptime(label,"%Y-%m-%d %H:%M").replace(tzinfo=CN)
            if bar_stamp.strftime("%H:%M") not in _LABEL_END[timeframe] or bar_stamp.astimezone(timezone.utc)>now:
                raise ValueError
            if previous is not None and bar_stamp<=previous:
                raise ValueError
            previous=bar_stamp
            numerical={}
            for key in ("open","high","low","close","volume","amount"):
                val=item.get(key)
                if type(val) not in (int,float) or not isfinite(val):
                    raise ValueError
                numerical[key]=val
            if numerical["low"]<=0 or numerical["high"]<max(numerical["open"],numerical["close"],numerical["low"]) or numerical["low"]>min(numerical["open"],numerical["close"],numerical["high"]) or numerical["volume"]<0 or numerical["amount"]<0:
                raise ValueError
            safe.append({"label":label,**numerical,"is_partial_bar":True,"bar_finality":"NOT_VERIFIED"})
    except (KeyError,ValueError,TypeError,OverflowError):
        return {**base,"status":"INVALID_CACHE"}
    return {
        **base,"ok":True,"status":"PASS_RESEARCH_ONLY","repo_sha":sha,
        "sequence":obj.get("sequence"),"source_age_seconds":round(age,2),
        "symbol":symbol,"timeframe":timeframe,"rows":safe,
        "timestamp_semantic":"BAR_END_GRID_MATCH_HISTORICAL_ONLY",
        "volume_units":"NOT_VERIFIED","crosscheck":"NOT_VERIFIED",
    }

