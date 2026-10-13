"""Read-only, isolated TickFlow Premium minute observation (not canonical/trade)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    if isinstance(frame, dict):
        # The official SDK's as_dataframe=False compact schema is columnar.
        # tickflow[realtime] does NOT install optional pandas; do not require
        # it in an AWS service or silently assume a DataFrame/DatetimeIndex.
        # The installed SDK explicitly permits missing "amount" and the
        # DataFrame helper silently fills it with zero. Never invent turnover:
        # preserve None + availability UNKNOWN on the research-only route.
        required = ("timestamp", "open", "high", "low", "close", "volume")
        if any(not isinstance(frame.get(key), (list, tuple)) for key in required):
            raise ValueError("missing compact SDK column")
        amount_present = "amount" in frame
        keys = (*required, "amount") if amount_present else required
        if amount_present and not isinstance(frame["amount"], (list,tuple)):
            raise ValueError("missing compact SDK column")
        sizes = {len(frame[key]) for key in keys}
        if len(sizes) != 1:
            raise ValueError("compact SDK column lengths differ")
        count = sizes.pop()
        if not 4 <= count <= _ALLOWED_PERIODS[timeframe]:
            raise ValueError("insufficient or unbounded history")
        records = [{**{key:frame[key][i] for key in keys},
                    **({} if amount_present else {"amount":None,"_sdk_amount_omitted":True})}
                   for i in range(count)]
    elif hasattr(frame, "to_dict"):
        records = frame.to_dict(orient="records")
    else:
        raise ValueError("unexpected SDK data type")
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
        current_shanghai_day = sh.date() == now_utc.astimezone(CN).date()
        if sh.second != 0 or sh.microsecond or sh.strftime("%H:%M") not in _LABEL_END[timeframe]:
            if current_shanghai_day:
                # Current provider response can contain a *forming* candle
                # labeled by its opening time (e.g. 13:00). Never turn it
                # into a historical BAR_END observation. Quarantine only this
                # session; historical off-grid labels remain a hard failure.
                continue
            raise ValueError("unexpected Shanghai regular-session grid")
        # Reject future bars, but do not pretend already elapsed means exchange-final.
        if stamp > now_utc:
            # The provider can label a still-forming 15m/60m candle by the
            # future end boundary. Drop it from research output, not all bars.
            # A future trading *date* cannot be explained by a forming bar.
            if sh.date() != now_utc.astimezone(CN).date():
                raise ValueError("future trading date")
            continue
        try:
            op=_number(raw,"open","open_price")
            hi=_number(raw,"high","high_price")
            lo=_number(raw,"low","low_price")
            cl=_number(raw,"close","close_price")
            vol=_number(raw,"volume","vol")
            amount_unknown = raw.get("_sdk_amount_omitted") is True
            amt = None if amount_unknown else _number(raw,"amount","turnover")
        except ValueError:
            if current_shanghai_day:
                # An unfinished today's bar can have missing quotes/turnover;
                # never backfill invented OHLC or claim it is a closed bar.
                # Historical invalid rows remain a fail-closed hard error.
                continue
            raise
        invalid_reason=None
        if op <= 0 or cl <= 0 or lo <= 0 or hi <= 0:
            invalid_reason="invalid OHLCVA nonpositive"
        elif hi < max(op,cl,lo):
            invalid_reason="invalid OHLCVA high below body"
        elif lo > min(op,cl,hi):
            invalid_reason="invalid OHLCVA low above body"
        elif vol < 0:
            invalid_reason="invalid OHLCVA negative volume"
        elif amt is not None and amt < 0:
            invalid_reason="invalid OHLCVA negative amount"
        if invalid_reason is not None:
            if current_shanghai_day:
                # Current-day partial/unqualified bar only; the reader still
                # requires the last due 15m/60m grid label before any data
                # can be surfaced even for research.
                continue
            raise ValueError(invalid_reason)
        bars.append({
            "label": sh.strftime("%Y-%m-%d %H:%M"),
            "open":op,"high":hi,"low":lo,"close":cl,
            "volume":vol,"amount":amt,
            "amount_availability":"SDK_OMITTED" if amount_unknown else "PRESENT_UNVERIFIED",
            "is_partial_bar": True,
            "bar_finality": "NOT_VERIFIED",
        })
    if len(bars)<4:
        raise ValueError("no sufficient historical closed-time candidates")
    return bars

def _expected_closed_grid_label(now_utc: datetime, timeframe: str) -> datetime | None:
    """Return last scheduled A-share BAR_END label due, not finality evidence.

    The 90s grace addresses ordinary provider publishing delay; if a due
    Shanghai session boundary is absent, label progression is not ready for
    live research. No exchange calendar is available: weekdays on holidays
    intentionally fail closed rather than invent an open market.
    """
    sh_now=now_utc.astimezone(CN)
    if sh_now.weekday()>=5:
        return None
    cutoff=sh_now-timedelta(seconds=90)
    candidates=[]
    for clock in _LABEL_END[timeframe]:
        hour,minute=map(int,clock.split(":"))
        proposed=sh_now.replace(hour=hour,minute=minute,second=0,microsecond=0)
        if proposed<=cutoff and proposed.date()==sh_now.date():
            candidates.append(proposed)
    return max(candidates) if candidates else None


def build_observation(client: Any, *, now_utc: datetime, repo_sha: str, sequence: int,
                      symbols: tuple[str,...]=SYMBOLS) -> dict:
    if now_utc.tzinfo is None or not re.fullmatch("[0-9a-f]{40}",repo_sha):
        raise ValueError("invalid wall clock or source revision")
    if type(sequence) is not int or sequence < 1:
        raise ValueError("invalid monotonic sequence")
    if (not symbols or len(symbols)>len(SYMBOLS)
            or len(set(symbols))!=len(symbols)
            or any(not isinstance(x,str) or x not in SYMBOLS for x in symbols)):
        # Hard billing/entitlement boundary: no arbitrary A-share scan until
        # separate reviewed quota and license approvals.
        raise ValueError("unapproved symbols")
    output={}
    for index,symbol in enumerate(symbols):
        frames={}
        for interval, n in _ALLOWED_PERIODS.items():
            # SDK's isolated Premium Kline contract was separately verified on AWS.
            stage=f"S{index}_{interval.upper()}_FETCH"
            try:
                frame=client.klines.get(symbol, period=interval,count=n,
                                        adjust="none",as_dataframe=False)
            except Exception as exc:
                exc._tickflow_stage=stage
                raise
            stage=f"S{index}_{interval.upper()}_NORMALIZE"
            try:
                bars=normalize_bars(frame,interval,now_utc=now_utc)
            except Exception as exc:
                exc._tickflow_stage=stage
                raise
            frames[interval]={"rows":bars,
                 "quarantined_unverified_rows_count":(
                     len(frame["timestamp"])-len(bars)
                     if isinstance(frame,dict) and isinstance(frame.get("timestamp"),list)
                     else 0
                 ),
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
             *, path: str=DEFAULT_PATH, now_utc:datetime|None=None,
             research_mode: str="session_progress") -> dict:
    """Bounded research-only read, with explicitly separate historical mode.

    session_progress requires the last due intraday BAR_END label; historical
    permits verified-shape prior bars even if the current session is missing.
    Neither mode asserts exchange finality or source/Radar eligibility.
    """
    base={
        "ok":False,"provider":_SOURCE,"provider_first_target":True,
        "research_only":True, "bar_finality":"NOT_VERIFIED",
        "currentness":"UNPROVEN", "source_arbiter_admission":"BLOCKED",
        "radar_admission":"BLOCKED","live_trade":False,"can_confirm_signal":False,
        "canonical_write_authorized":False, "provider_requests":0,
        "research_mode":research_mode if research_mode in
            ("session_progress","historical_only") else "INVALID",
        "exchange_bar_finality":"NOT_VERIFIED",
    }
    if (not isinstance(symbol,str) or symbol not in SYMBOLS
            or timeframe not in _ALLOWED_PERIODS
            or research_mode not in ("session_progress","historical_only")
            or type(limit)!=int or not 1<=limit<=96):
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
    # Strict live-session provenance never inherits the slower off-hours
    # refresh schedule. Historical-only read gets a 6m bounded tolerance
    # after close (collector polls every 300s), or 18m on weekends (900s).
    # A 6m old snapshot is NOT represented as fresh/current live data.
    sh_now=now.astimezone(CN)
    historical_max_age=1080 if sh_now.weekday()>=5 else 360
    max_age=(historical_max_age if research_mode=="historical_only"
             else MAX_AGE_SECONDS)
    if age < -5 or age > max_age:
        return {**base,"status":"STALE","age_seconds":round(age,2),
                "max_age_seconds":max_age}
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
            for key in ("open","high","low","close","volume"):
                val=item.get(key)
                if type(val) not in (int,float) or not isfinite(val):
                    raise ValueError
                numerical[key]=val
            availability=item.get("amount_availability")
            amount=item.get("amount")
            if availability=="SDK_OMITTED" and amount is None:
                numerical["amount"]=None
            elif availability=="PRESENT_UNVERIFIED" and type(amount) in (int,float) and isfinite(amount) and amount>=0:
                numerical["amount"]=amount
            else:
                raise ValueError
            if (numerical["low"]<=0
                    or numerical["high"]<max(numerical["open"],numerical["close"],numerical["low"])
                    or numerical["low"]>min(numerical["open"],numerical["close"],numerical["high"])
                    or numerical["volume"]<0):
                raise ValueError
            safe.append({"label":label,**numerical,"amount_availability":availability,
                "is_partial_bar":True,"bar_finality":"NOT_VERIFIED"})
    except (KeyError,ValueError,TypeError,OverflowError):
        return {**base,"status":"INVALID_CACHE"}
    expected=_expected_closed_grid_label(now,timeframe)
    latest=bar_stamp
    progress="NOT_DUE_OR_NO_SESSION_CALENDAR"
    if expected is not None:
        if latest < expected:
            if research_mode=="session_progress":
                # Do not allow a stale/partial session to pass currentness
                # merely because the poller rewrites the cache.
                return {
                    **base, "status":"BAR_LABEL_BEHIND_SESSION",
                    "source_age_seconds":round(age,2),
                    "expected_grid_progress":"NOT_OBSERVED",
                    "bar_finality":"NOT_VERIFIED",
                    "rows":[],
                }
            progress="DUE_LABEL_NOT_OBSERVED_HISTORICAL_ONLY"
        else:
            progress="DUE_LABEL_PRESENT_NOT_FINALITY_PROOF"
    label_age=(now-latest.astimezone(timezone.utc)).total_seconds()
    if research_mode=="historical_only":
        # Stated as limited historical use, never an eligible live provider.
        return {
            **base,"ok":True,"status":"PASS_HISTORICAL_ONLY","repo_sha":sha,
            "expected_grid_progress":progress,
            "last_bar_end_label_age_seconds":round(max(0,label_age),2),
            "latency_scope":"BAR_END_LABEL_AGE_NOT_PROVIDER_LATENCY",
            "max_age_seconds":max_age,
            "sequence":obj.get("sequence"),"source_age_seconds":round(age,2),
            "symbol":symbol,"timeframe":timeframe,"rows":safe,
            "timestamp_semantic":"BAR_END_GRID_MATCH_HISTORICAL_ONLY",
            "volume_units":"NOT_VERIFIED","crosscheck":"NOT_VERIFIED",
            "currentness":"UNPROVEN","session_currentness":"NOT_VERIFIED",
        }
    return {
        **base,"ok":True,"status":"PASS_RESEARCH_ONLY","repo_sha":sha,
        "expected_grid_progress":progress,
        "last_bar_end_label_age_seconds":round(max(0,label_age),2),
        "latency_scope":"BAR_END_LABEL_AGE_NOT_PROVIDER_LATENCY",
        "sequence":obj.get("sequence"),"source_age_seconds":round(age,2),
        "symbol":symbol,"timeframe":timeframe,"rows":safe,
        "timestamp_semantic":"BAR_END_GRID_MATCH_HISTORICAL_ONLY",
        "volume_units":"NOT_VERIFIED","crosscheck":"NOT_VERIFIED",
    }

