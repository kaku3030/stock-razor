"""Counterexamples for an unversioned/ad-hoc amount-volume envelope screen."""
from copy import deepcopy
import json

import pytest
from data_provider import tickflow_evidence_checkpoints as evidence
from tests.test_tickflow_evidence_checkpoints import NOW,snapshot


def row(volume,amount):
    return dict(low=2.0,high=2.0,volume=volume,amount=amount)


def test_exact_vwap_and_quantity_envelope_are_distinct_hypotheses():
    rows=[row(100,20000),row(100,20050),row(100,20150),row(100,20300),
          row(100,200),row(0,0),row(0,1),row(100,None),row(100,0)]
    before=deepcopy(rows)
    result=evidence.audit_amount_volume_rows(rows)
    assert rows==before
    assert result["positive_rows"]==5
    assert result["scale1_exact_inside_rows"]==1
    assert result["scale100_exact_inside_rows"]==1
    assert result["scale100_exact_outside_rows"]==4
    assert result["outside_fit_half_raw_unit_rows"]==1
    assert result["outside_fit_one_raw_unit_rows"]==2
    assert result["outside_unexplained_one_raw_unit_rows"]==2
    assert result["zero_volume_zero_amount_rows"]==1
    assert result["zero_volume_positive_amount_rows"]==1
    assert result["missing_amount_rows"]==1
    assert result["positive_volume_zero_amount_rows"]==1


def test_decimal_threshold_equality_and_outside_remain_distinct():
    # Upper amount envelope is exactly(2+1e-5)*(100+1)*100.
    result=evidence.audit_amount_volume_rows([row(100,20200.101),row(100,20200.10101)])
    assert result["outside_fit_one_raw_unit_rows"]==1
    assert result["outside_unexplained_one_raw_unit_rows"]==1


@pytest.mark.parametrize("bad",[[],[row(True,200)], [row(100,float("nan"))],
                             [row(-1,200)],[row(1,-1)],[row(1,1e19)]])
def test_invalid_numeric_data_never_yields_diagnostic_pass(bad):
    with pytest.raises(ValueError):
        evidence.audit_amount_volume_rows(bad)


def test_read_diagnostics_reuses_one_snapshot_without_exporting_quotes(tmp_path):
    path=tmp_path/"cache.json";data=snapshot();path.write_text(json.dumps(data))
    result=evidence.read_unit_diagnostics(path=path,now_utc=NOW)
    assert result["status"]=="UNIT_HYPOTHESIS_DIAGNOSTICS_ONLY"
    assert result["formula_id"]==evidence.UNIT_FORMULA and len(result["frames"])==20
    assert result["units_contract"]=="NOT_VERIFIED"
    assert result["provider_requests"]==0 and result["live_trade"] is False
    assert result["source_sha"]=="a"*40 and result["sequence"]==1
    assert '"low"' not in json.dumps(result) and "2026-10-23 15:00" not in json.dumps(result)
    data["symbols"]["159209.SZ"]["1m"]["rows"].pop(0);path.write_text(json.dumps(data))
    assert evidence.read_unit_diagnostics(path=path,now_utc=NOW)["status"]=="UNIT_CACHE_VALIDATION_BLOCKED"


def test_units_sentinel_keeps_real_read_validation_and_no_fallback(tmp_path,monkeypatch):
    import ast
    from pathlib import Path
    path=tmp_path/"cache.json";path.write_text(json.dumps(snapshot()))
    original=evidence.read_unit_diagnostics
    monkeypatch.setattr(evidence,"read_unit_diagnostics",lambda:original(path=path,now_utc=NOW))
    tree=ast.parse(Path("realtime_monitor/readonly_mcp_server.py").read_text())
    handler=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="get_cn_market_data")
    assert len(handler.decorator_list)==1
    handler.decorator_list=[]
    namespace={}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[handler],type_ignores=[])),"<mcp>","exec"),namespace)
    result=namespace["get_cn_market_data"]("TICKFLOW:UNITS")
    assert result["status"]=="UNIT_HYPOTHESIS_DIAGNOSTICS_ONLY"
    assert len(result["frames"])==20 and result["units_contract"]=="NOT_VERIFIED"
    path.write_text("broken")
    blocked=namespace["get_cn_market_data"]("TICKFLOW:UNITS")
    assert blocked["status"]=="UNIT_CACHE_VALIDATION_BLOCKED" and "frames" not in blocked
