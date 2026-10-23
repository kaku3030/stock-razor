from datetime import datetime, timedelta, timezone
import json

import pytest
from data_provider import tickflow_evidence_checkpoints as evidence
from data_provider.cn_tickflow_research_cache import build_observation
from tests.test_cn_tickflow_research_cache import FakeClient, frame

NOW = datetime(2026,10,23,7,6,tzinfo=timezone.utc)


def snapshot(now=NOW, sequence=1):
    client = FakeClient()
    def get(symbol, *, period, count, as_dataframe, adjust, start_time=None, end_time=None):
        if period == "1d":
            df = frame(period)
            rows = []
            for i in range(60):
                r = df.iloc[0].to_dict()
                r["timestamp"] = int((NOW-timedelta(days=60-i)).astimezone(timezone(timedelta(hours=8))).replace(hour=0,minute=0,second=0).timestamp())*1000
                rows.append(r)
            return {k:[r[k] for r in rows] for k in ("timestamp","open","high","low","close","volume","amount")}
        # Core reader requires every due current-day label. Reuse the real grid.
        from data_provider.cn_tickflow_research_cache import _LABEL_END, CN
        rows = []
        for label in sorted(_LABEL_END[period]):
            stamp = datetime.fromisoformat("2026-10-23T"+label).replace(tzinfo=CN)
            rows.append(dict(timestamp=int(stamp.timestamp())*1000,open=1.5,high=1.7,low=1.3,
                             close=1.6,volume=100,amount=160))
        return {k:[r[k] for r in rows] for k in rows[0]}
    client.klines.get = get
    return build_observation(client,now_utc=now,repo_sha="a"*40,sequence=sequence,
                              include_supplemental=True)


def test_manifest_revalidates_all_frames_and_contains_no_prices():
    doc = evidence.manifest_from_observation(snapshot(),endpoint="AWS",now_utc=NOW)
    assert len(doc["frames"]) == 20
    assert len(doc["frames"]["159611.SZ:1m"]) == 240
    assert '1.7' not in json.dumps(doc)
    assert doc["provenance_verified"] is False and doc["live_trade"] is False
    broken = snapshot()
    broken["symbols"]["159611.SZ"]["1m"]["rows"].pop(0)
    with pytest.raises(ValueError):
        evidence.manifest_from_observation(broken,endpoint="AWS",now_utc=NOW)


def test_revision_observation_preserves_baseline_and_never_claims_finality(tmp_path):
    first = snapshot()
    result = evidence.record_postclose_checkpoint(first,root=tmp_path,now_utc=NOW)
    assert result["status"] == "BASELINE_RECORDED_AWAITING_AFTER20"
    baseline = tmp_path/"2026-10-23/baseline.json"
    before = baseline.read_bytes()
    after = NOW.replace(hour=12,minute=6)  # Shanghai20:06
    second = snapshot(after,sequence=2)
    second["symbols"]["159611.SZ"]["1m"]["rows"][-1]["close"] = 1.61
    result = evidence.record_postclose_checkpoint(second,root=tmp_path,now_utc=after)
    assert result["comparison"]["status"] == "REVISION_OBSERVED"
    assert result["comparison"]["changed_rows"] == 1
    assert result["comparison"]["changed_fields"]["close"] == 1
    assert baseline.read_bytes() == before
    again = evidence.record_postclose_checkpoint(second,root=tmp_path,now_utc=after)
    assert again["comparison"] == result["comparison"]
    assert result["bar_finality"] == "NOT_VERIFIED" and result["radar_admission"] == "BLOCKED"


def test_dual_endpoints_require_distinct_capture_and_aligned_clock():
    first = evidence.manifest_from_observation(snapshot(),endpoint="AWS",now_utc=NOW)
    second = evidence.manifest_from_observation(snapshot(),endpoint="WINDOWS",now_utc=NOW)
    assert evidence.compare_manifests(first,second,dual_endpoint=True)["status"] == "PAIR_VALUES_MATCH_RESEARCH_ONLY"
    assert evidence.compare_manifests(first,first,dual_endpoint=True)["status"] == "EVIDENCE_INVALID"
    later = NOW+timedelta(minutes=2)
    stale = evidence.manifest_from_observation(snapshot(later),endpoint="WINDOWS",now_utc=later)
    assert evidence.compare_manifests(first,stale,dual_endpoint=True)["status"] == "EVIDENCE_INVALID"
    second["frames"]["159611.SZ:1m"].pop("2026-10-23 09:31")
    assert evidence.compare_manifests(first,second,dual_endpoint=True)["status"] == "EVIDENCE_INVALID"


def test_immutable_write_corruption_quota_and_late_baseline(tmp_path,monkeypatch):
    late = NOW.replace(hour=10)
    data = snapshot(late)
    result = evidence.record_postclose_checkpoint(data,root=tmp_path,now_utc=late)
    assert result["baseline_timing"] == "LATE_BASELINE_LIMITED"
    path = tmp_path/"2026-10-23/baseline.json"
    assert evidence.write_immutable(path,{"changed":True}) is False
    path.write_text("broken")
    with pytest.raises(ValueError):
        evidence.record_postclose_checkpoint(data,root=tmp_path,now_utc=late)
    monkeypatch.setattr(evidence,"MAX_STORE",1)
    assert evidence.record_postclose_checkpoint(data,root=tmp_path/"other",now_utc=late)["status"] == "EVIDENCE_QUOTA_BLOCKED"


def test_worker_evidence_io_failure_stays_explicit_without_throwing(monkeypatch):
    from scripts import run_cn_tickflow_research_worker as worker
    def fail(*args,**kwargs):
        raise OSError("private detail")
    monkeypatch.setattr(worker,"record_postclose_checkpoint",fail)
    result = worker._postclose_evidence({},NOW)
    assert result["status"] == "EVIDENCE_IO_BLOCKED"
    assert "private detail" not in str(result)
    assert result["live_trade"] is False


def test_rehashed_missing_due_grid_and_malformed_clock_fail_closed():
    from copy import deepcopy
    doc = evidence.manifest_from_observation(snapshot(),endpoint="AWS",now_utc=NOW)
    for mutate in (
        lambda d: d["frames"]["159611.SZ:1m"].pop("2026-10-23 09:31"),
        lambda d: d.update(observed_at_utc=17),
        lambda d: d.update(live_trade=True),
    ):
        broken = deepcopy(doc)
        mutate(broken)
        broken["integrity_sha256"] = evidence._hash({k:v for k,v in broken.items() if k!="integrity_sha256"})
        assert evidence.compare_manifests(doc,broken,now_utc=NOW)["status"] == "EVIDENCE_INVALID"


def test_restarted_worker_sequence_does_not_hide_revision_and_missing_baseline(tmp_path):
    first = snapshot(sequence=1000)
    evidence.record_postclose_checkpoint(first,root=tmp_path,now_utc=NOW)
    later = NOW.replace(hour=12,minute=6)
    restarted = snapshot(later,sequence=1)
    result = evidence.record_postclose_checkpoint(restarted,root=tmp_path,now_utc=later)
    assert result["comparison"]["status"] == "NO_REVISION_OBSERVED_NOT_FINAL"
    assert result["bar_finality"] == "NOT_VERIFIED"
    # A new process reads the persisted baseline; no process-local state is needed.
    assert evidence.checkpoint_status(root=tmp_path,day="2026-10-23",now_utc=later) == result
    assert evidence.record_postclose_checkpoint(restarted,root=tmp_path/"absent",now_utc=later)["status"] == "BASELINE_MISSING"
    with pytest.raises(ValueError):
        evidence.checkpoint_status(root=tmp_path,day="2026-10-23",now_utc=NOW-timedelta(hours=1))


def test_evidence_sentinel_keeps_public_tool_and_exports_only_summary(tmp_path,monkeypatch):
    import ast
    from pathlib import Path
    evidence.record_postclose_checkpoint(snapshot(),root=tmp_path,now_utc=NOW)
    original = evidence.checkpoint_status
    def status(**kwargs):
        return original(root=tmp_path,day="2026-10-23",now_utc=NOW)
    monkeypatch.setattr(evidence,"checkpoint_status",status)
    tree = ast.parse(Path("realtime_monitor/readonly_mcp_server.py").read_text())
    nodes = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in
             ("_read_tickflow_evidence","get_cn_market_data")]
    handler = next(n for n in nodes if n.name=="get_cn_market_data")
    assert len(handler.decorator_list)==1 and ast.unparse(handler.decorator_list[0])=="mcp.tool()"
    private = next(n for n in nodes if n.name=="_read_tickflow_evidence")
    assert not private.decorator_list
    handler.decorator_list=[]
    ns={}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),"<mcp>","exec"),ns)
    result = ns["get_cn_market_data"]("TICKFLOW:EVIDENCE")
    assert result["status"]=="BASELINE_RECORDED_AWAITING_AFTER20"
    assert "frames" not in result and "source_sha" not in result
    assert result["provider_requests"]==0 and result["radar_admission"]=="BLOCKED"


def test_capture_default_is_offline_and_comparison_requires_valid_private_files(monkeypatch,capsys,tmp_path):
    import sys
    from scripts import capture_tickflow_endpoint_evidence as capture
    monkeypatch.setattr(sys,"argv",["capture"])
    assert capture.main()==0
    assert json.loads(capsys.readouterr().out)["status"]=="NOT_EXECUTED_OPT_IN_REQUIRED"
    monkeypatch.setattr(sys,"argv",["capture","--compare",str(tmp_path/"missing"),str(tmp_path/"missing2")])
    assert capture.main()==2
    assert json.loads(capsys.readouterr().out)["status"]=="EVIDENCE_INVALID"
