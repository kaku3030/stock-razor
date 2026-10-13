"""Historical OHLC precision evidence; zero tolerance-based price admission."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from copy import deepcopy

import pytest

from data_provider.cn_tickflow_research_cache import (
    normalize_bars, _vendor_ohlc_float_gap_bucket,
)
from scripts.run_cn_tickflow_research_worker import (
    _ohlc_float_gap_bucket, _normalize_rejection_reason,
)

SH=ZoneInfo("Asia/Shanghai")
NOW=datetime(2026,10,14,0,0,tzinfo=timezone.utc)


def bars():
    labels=("09:45","10:00","10:15","10:30","10:45","11:00","11:15","11:30")
    return {
        "timestamp":[int(datetime.fromisoformat(f"2026-10-13T{t}").replace(tzinfo=SH).timestamp())*1000 for t in labels],
        "open":[1.5]*8,"high":[1.7]*8,"low":[1.3]*8,
        "close":[1.6]*8,"volume":[100]*8,"amount":[160]*8,
    }


@pytest.mark.parametrize("diff, expected",[
    (0.000005,"WITHIN_1E_MINUS_5"),
    (0.000010,"WITHIN_1E_MINUS_5"),
    (0.000020,"OVER_1E_MINUS_5"),
    (0.000100,"OVER_1E_MINUS_5"),
])
def test_historical_high_below_body_stays_rejected_with_only_fixed_bucket(diff,expected):
    raw=bars()
    raw["high"][0]=1.6-diff
    before=deepcopy(raw)
    with pytest.raises(ValueError,match="invalid OHLCVA high below body") as capture:
        normalize_bars(raw,"15m",now_utc=NOW)
    error=capture.value
    assert getattr(error,"_tickflow_ohlc_float_gap_bucket") == expected
    error._tickflow_stage="S0_15M_NORMALIZE"
    assert _normalize_rejection_reason(error)=="OHLCVA_HIGH_LT_BODY"
    assert _ohlc_float_gap_bucket(error)==expected
    assert raw==before  # never round/repair/write prices


def test_low_above_body_is_equivalently_strict():
    raw=bars()
    raw["low"][0]=1.500005
    with pytest.raises(ValueError,match="invalid OHLCVA low above body") as capture:
        normalize_bars(raw,"15m",now_utc=NOW)
    err=capture.value
    assert err._tickflow_ohlc_float_gap_bucket=="WITHIN_1E_MINUS_5"
    err._tickflow_stage="S0_15M_NORMALIZE"
    assert _normalize_rejection_reason(err)=="OHLCVA_LOW_GT_BODY"


def test_unqualified_precision_evidence_never_claims_tolerance():
    assert _vendor_ohlc_float_gap_bucket(1.5,0.0,1.3,1.6)=="UNKNOWN"
    assert _vendor_ohlc_float_gap_bucket(1.5,float("nan"),1.3,1.6)=="UNKNOWN"
    err=ValueError("invalid OHLCVA high below body")
    err._tickflow_ohlc_float_gap_bucket="WITHIN_1E_MINUS_5"
    assert _ohlc_float_gap_bucket(err)=="UNKNOWN"
    err._tickflow_stage="S0_15M_FETCH"
    assert _ohlc_float_gap_bucket(err)=="UNKNOWN"
    err._tickflow_stage="S0_15M_NORMALIZE"
    err._tickflow_ohlc_float_gap_bucket="1.599995"
    assert _ohlc_float_gap_bucket(err)=="UNKNOWN"


def test_valid_historical_rows_unchanged_and_not_exchange_final():
    out=normalize_bars(bars(),"15m",now_utc=NOW)
    assert len(out)==8
    assert all(item["bar_finality"]=="NOT_VERIFIED" and item["is_partial_bar"] for item in out)


def test_cloud_audit_projection_never_prints_unbounded_gap():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    worker=(root/"scripts/run_cn_tickflow_research_worker.py").read_text(encoding="utf-8")
    audit=(root/"scripts/audit_cn_tickflow_research_runtime.py").read_text(encoding="utf-8")
    workflow=(root/".github/workflows/audit-cn-tickflow-live-research.yml").read_text(encoding="utf-8")
    assert '"failure_ohlc_float_gap_bucket":_ohlc_float_gap_bucket(exc)' in worker
    assert '"failure_ohlc_float_gap_bucket":"UNKNOWN"' in audit
    assert "WITHIN_1E_MINUS_5" in workflow and "OVER_1E_MINUS_5" in workflow
    assert 'assert d.get("radar_admission")=="BLOCKED"' in workflow
    assert 'assert d.get("live_trade")=="NO"' in workflow
