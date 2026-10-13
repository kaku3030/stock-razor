from datetime import datetime, timezone
from scripts.audit_cn_tickflow_research_runtime import eastmoney_tencent_historical_grid_shadow

DATES=("2026-10-08","2026-10-09","2026-10-12")
GRID=("10:30","11:30","14:00","15:00")
NOW=datetime(2026,10,13,7,15,tzinfo=timezone.utc)

def rows(provider, days=DATES, delta=0.0):
    items=[]
    for day in days:
        for clock in GRID:
            label=f"{day} {clock}"
            x={"label":label,"provider":provider,"quality_flags":[],
               "open":1.20+delta,"high":1.22+delta,"low":1.19+delta,"close":1.21+delta}
            if provider=="eastmoney": x["provider_label_raw"]=label
            items.append(x)
    return items

def cache(items=None):
    return {"schema":"stock_razor_cn_eastmoney_observation_v1",
            "research_only":True,"radar_admission":"BLOCKED",
            "live_trade":False,"emitted_at_utc":NOW.isoformat(),
            "symbols":{"159611":{"timeframes":{"60m":{
                "status":"PASS","adjustment":"NONE","provider_used":"eastmoney",
                "timestamp_semantic":"UNKNOWN","timestamp_qualification":None,
                "rows":rows("eastmoney") if items is None else items,
            }}}}}

def check(ref=None, external=None, qualified=True):
    return eastmoney_tencent_historical_grid_shadow(
        cache() if ref is None else ref,
        rows("tencent",delta=.0003) if external is None else external,
        symbol="159611",timeframe="60m",qualified=qualified,now_utc=NOW)

def test_positive_research_only_witness():
    result=check()
    assert result=="HISTORICAL_GRID_PRICE_ALIGNED_RESEARCH_ONLY"
    assert "2026" not in result and "1.2" not in result

def test_fail_closed_for_bad_qualification_and_insufficient_sessions():
    assert check(qualified=False)=="TENCENT_UNQUALIFIED"
    assert check(ref=cache(rows("eastmoney",days=DATES[:2])))=="INSUFFICIENT_SHARED_COMPLETE_SESSIONS"

def test_forged_lineage_label_and_order_fail_closed():
    for field in ("provider","provider_label_raw","label"):
        sample=rows("eastmoney")
        sample[0][field]="fake"
        assert check(ref=cache(sample))=="INVALID_REFERENCE"

def test_grid_agreement_does_not_mask_price_disagreement():
    assert check(external=rows("tencent",delta=.003))=="HISTORICAL_GRID_ALIGNED_PRICE_DIVERGENCE"

def test_production_semantics_remain_unknown():
    ref=cache()
    ref["symbols"]["159611"]["timeframes"]["60m"]["timestamp_semantic"]="BAR_END"
    assert check(ref=ref)=="UNQUALIFIED_REFERENCE_LINEAGE"

def test_stale_reference_or_nan_price_fail_closed():
    ref=cache()
    ref["emitted_at_utc"]="2026-10-12T00:00:00+00:00"
    assert check(ref=ref)=="NO_FRESH_REFERENCE"
    broken=rows("eastmoney")
    broken[0]["open"]=float("nan")
    assert check(ref=cache(broken))=="INVALID_REFERENCE"

def test_workflow_enforces_schema_and_trade_gates():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    workflow=(root/".github/workflows/audit-cn-tickflow-live-research.yml").read_text(encoding="utf-8")
    assert "eastmoney_historical_grid_shadow" in workflow
    assert 'assert d.get("radar_admission")=="BLOCKED"' in workflow
    assert 'assert d.get("canonical_write")=="NO"' in workflow
