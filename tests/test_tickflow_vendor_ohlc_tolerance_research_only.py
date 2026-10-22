"""Official TickFlow OHLC <= 1e-5 remains non-mutating research ONLY."""
from copy import deepcopy
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

import pytest

from data_provider.cn_tickflow_research_cache import (
    normalize_bars,build_observation,atomic_publish,
    read_cn_tickflow_research_data,
)

SH=ZoneInfo("Asia/Shanghai")
NOW=datetime(2026,10,14,0,0,tzinfo=timezone.utc)
LABELS={
    "15m": ("09:45","10:00","10:15","10:30","10:45","11:00","11:15","11:30"),
    "60m": ("10:30","11:30","14:00","15:00"),
}

def series(tf="15m", day="2026-10-13"):
    labels=LABELS[tf]
    return {
        "timestamp":[int(datetime.fromisoformat(f"{day}T{t}").replace(tzinfo=SH).timestamp())*1000 for t in labels],
        "open":[1.5]*len(labels),"high":[1.7]*len(labels),
        "low":[1.3]*len(labels),"close":[1.6]*len(labels),
        "volume":[100]*len(labels),"amount":[160]*len(labels),
    }

def collect(rows, tf="15m"):
    return normalize_bars(rows,tf,now_utc=NOW)


@pytest.mark.parametrize("field,value",[
    ("high",1.599995),
    ("high",1.59999),
    ("low",1.500005),
    ("low",1.50001),
])
def test_vendor_precision_tolerance_research_only_preserves_exact_raw_value(field,value):
    raw=series()
    raw[field][0]=value
    before=deepcopy(raw)
    bars=collect(raw)
    assert len(bars)==8
    assert raw==before
    assert bars[0][field]==value
    assert bars[0]["ohlc_validation"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    assert bars[0]["bar_finality"]=="NOT_VERIFIED"
    assert bars[0]["is_partial_bar"] is True
    assert all(x["ohlc_validation"]=="STRICT" for x in bars[1:])


@pytest.mark.parametrize("field,value,error",[
    ("high",1.59998,"high below body"),
    ("low",1.50002,"low above body"),
])
def test_above_vendor_bound_historical_rejected_with_original_failure(field,value,error):
    raw=series()
    raw[field][0]=value
    with pytest.raises(ValueError,match=error) as context:
        collect(raw)
    assert context.value._tickflow_ohlc_float_gap_bucket=="OVER_1E_MINUS_5"


def test_historical_vendor_float_gap_with_off_tick_open_is_rejected():
    # The 5e-6 high/body gap is small, but another field is 0.00045 CNY
    # off the ETF lattice. Neither current nor *past* days may launder it.
    raw=series()
    raw["high"][0]=1.599995
    raw["open"][0]=1.50045
    with pytest.raises(ValueError, match="high below body"):
        collect(raw)


class Client:
    class Klines:
        def get(self,symbol,*,period,count,adjust,as_dataframe,start_time=None,end_time=None):
            rows=series(period)
            if symbol=="159611.SZ" and period=="15m":
                rows["high"][0]=1.599995
            return rows
    klines=Klines()


def test_private_cache_and_reader_revalidate_tolerance_and_deny_promotion(tmp_path):
    snap=build_observation(Client(),now_utc=NOW,repo_sha="a"*40,sequence=7)
    assert snap["radar_admission"]=="BLOCKED"
    assert snap["source_arbiter_admission"]=="BLOCKED"
    assert snap["canonical_write_authorized"] is False
    path=tmp_path/"private.json"
    atomic_publish(str(path),snap)
    result=read_cn_tickflow_research_data(
        "159611.SZ","15m",research_mode="historical_only",
        path=str(path),now_utc=NOW,limit=20)
    assert result["ok"] is True and result["status"]=="PASS_HISTORICAL_ONLY"
    assert result["rows"][0]["high"]==1.599995
    assert result["rows"][0]["ohlc_validation"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    assert result["can_confirm_signal"] is False
    assert result["exchange_bar_finality"]=="NOT_VERIFIED"
    assert result["bar_finality"]=="NOT_VERIFIED"
    assert result["radar_admission"]=="BLOCKED"
    assert result["source_arbiter_admission"]=="BLOCKED"

    modified=deepcopy(snap)
    row=modified["symbols"]["159611.SZ"]["15m"]["rows"][0]
    for high,validation in [
        (1.59998,"VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"),
        (1.599995,"STRICT"),
        (1.7,"VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"),
        (1.599995,"UNKNOWN"),
    ]:
        row["high"],row["ohlc_validation"]=high,validation
        atomic_publish(str(path),modified)
        rejected=read_cn_tickflow_research_data(
            "159611.SZ","15m",research_mode="historical_only",
            path=str(path),now_utc=NOW,limit=20)
        assert rejected["status"]=="INVALID_CACHE"
        assert rejected["ok"] is False


def test_reader_rejects_forged_historical_off_tick_float_row(tmp_path):
    snap=build_observation(Client(),now_utc=NOW,repo_sha="a"*40,sequence=7)
    forged=deepcopy(snap)
    row=forged["symbols"]["159611.SZ"]["15m"]["rows"][0]
    assert row["ohlc_validation"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    row["open"]=1.50045
    path=tmp_path/"forged-private.json"
    atomic_publish(str(path),forged)
    result=read_cn_tickflow_research_data(
        "159611.SZ","15m",research_mode="historical_only",
        path=str(path),now_utc=NOW,limit=20)
    assert result["ok"] is False
    assert result["status"]=="INVALID_CACHE"
    assert result["radar_admission"]=="BLOCKED"
    assert result["source_arbiter_admission"]=="BLOCKED"


def test_same_day_over_vendor_limit_is_still_quarantined():
    now=datetime(2026,10,13,5,18,tzinfo=timezone.utc)
    raw=series()
    labels=series(day="2026-10-13")
    # Current 13:15 label is due (Shanghai 13:18) but genuinely malformed.
    label=datetime(2026,10,13,13,15,tzinfo=SH)
    for key in ("timestamp","open","high","low","close","volume","amount"):
        raw[key]=raw[key][:7]
        raw[key].append(int(label.timestamp())*1000 if key=="timestamp"
                        else 1.59998 if key=="high"
                        else labels[key][0])
    count={}
    rows=normalize_bars(raw,"15m",now_utc=now,quarantine_counts=count)
    assert len(rows)==7
    assert count=={"TODAY_HIGH_BELOW_BODY":1}
    assert all(x["bar_finality"]=="NOT_VERIFIED" for x in rows)


@pytest.mark.parametrize("field,value", [
    ("high",1.599995), ("high",1.59999),
    ("low",1.500005), ("low",1.50001),
])
def test_current_session_small_vendor_float_research_only_not_final(field,value):
    # At 13:18 CST, the 13:15 label has cleared the 90-second buffer.
    # The candidate may preserve the unrounded vendor row only for research;
    # it must never certify strict OHLC, currentness or exchange finality.
    now=datetime(2026,10,13,5,18,tzinfo=timezone.utc)
    raw=series()
    for key in raw:
        raw[key]=raw[key][:7]
    label=datetime(2026,10,13,13,15,tzinfo=SH)
    raw["timestamp"].append(int(label.timestamp())*1000)
    for key,val in (("open",1.5),("high",1.7),("low",1.3),
                    ("close",1.6),("volume",100),("amount",160)):
        raw[key].append(value if key==field else val)
    count={}
    output=normalize_bars(raw,"15m",now_utc=now,quarantine_counts=count)
    assert len(output)==8
    assert count=={}
    assert all(x["bar_finality"]=="NOT_VERIFIED" and x["is_partial_bar"] is True
               for x in output)
    assert all(x["ohlc_validation"]=="STRICT" for x in output[:-1])
    assert output[-1]["ohlc_validation"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    assert output[-1][field]==value  # native float unchanged; no quantization


@pytest.mark.parametrize("field",["volume","amount"])
def test_ohlc_tolerance_never_bypasses_other_invalid_fields(field):
    raw=series()
    raw["high"][0]=1.599995
    raw[field][0]=-1
    with pytest.raises(ValueError):
        collect(raw)
    # An independent invalid-field defect cannot be hidden by a
    # simultaneous <=1e-5 serialization discrepancy.
