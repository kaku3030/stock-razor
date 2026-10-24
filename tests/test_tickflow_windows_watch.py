"""Offline contracts at child-process and persisted-receipt seams."""
from datetime import datetime, timezone
import hashlib
import json
import subprocess
from types import SimpleNamespace
import pytest
from scripts import audit_tickflow_windows_readonly as audit
from scripts import run_tickflow_windows_watch as watch

def frame():
    labels = ["2026-10-23T09:45:00+08:00", "2026-10-23T10:00:00+08:00",
              "2026-10-23T10:15:00+08:00", "2026-10-23T10:30:00+08:00"]
    return {"timestamp": [int(datetime.fromisoformat(t).timestamp()*1000) for t in labels],
            **{k: [v]*4 for k,v in {"open":1.05, "high":1.06, "low":1.04,
                                    "close":1.055,"volume":1000}.items()}}

def test_off_grid_extra_row_blocks():
    values = frame()
    for key in values:
        values[key].insert(0, values[key][0])
    values["timestamp"][0] = int(datetime.fromisoformat("2026-10-22T09:44:00+08:00").timestamp()*1000)
    result = audit.assess_compact(values, "15m", datetime.fromisoformat("2026-10-23T10:32:00+08:00"))
    assert result["research_due_labels_missing"] == 0
    assert result["invalid_grid_rows"] == 1
    assert result["status"] == result["research_progress_status"] == "BLOCKED_UNVERIFIED"

def test_empty_due_grid_on_weekend_is_never_pass():
    result = audit.assess_compact(frame(), "15m", datetime.fromisoformat("2026-10-24T10:32:00+08:00"))
    assert result["due_count"] == 0
    assert result["status"] == result["research_progress_status"] == "BLOCKED_UNVERIFIED"

def test_receipt_preserves_original_changes_without_prices():
    first = audit.frame_receipt(frame(), "15m", datetime.fromisoformat("2026-10-23T10:32:00+08:00"))
    values = frame()
    values["volume"][-1] += 1
    second = audit.frame_receipt(values, "15m", datetime.fromisoformat("2026-10-23T10:33:00+08:00"))
    assert first["row_receipts"][-1] != second["row_receipts"][-1]
    assert first["latest_bar_closed"] is False
    assert first["bar_finality"] == "NOT_VERIFIED"
    assert "1.055" not in json.dumps(first)

def deployed(tmp_path):
    files = {}
    for name in ("audit_tickflow_windows_readonly.py","run_tickflow_windows_watch.py"):
        path = tmp_path / name
        path.write_text("# synthetic child fixture")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    watch.atomic_write(tmp_path / "deployment.json", {"source_sha":"a"*40,"files":files})
    return tmp_path

def records():
    return [{"symbol":s,"timeframe":t,"data_source":"TICKFLOW_PREMIUM_DESKTOP_READONLY",
             "transport":"OFFICIAL_PYTHON_SDK_REST","sdk_version":"0.1.25",
             "trading_admission":"BLOCKED","radar_admission":"BLOCKED","live_trade":False,
             "provider_requests":1,"status":"PASS_RESEARCH_ONLY","bar_finality":"NOT_VERIFIED",
             "data_time_utc":"2026-10-23T02:00:00+00:00",
             "row_receipts":[{"bar_time_utc":"2026-10-23T02:00:00+00:00","ohlcv_sha256":"b"*64}]}
            for s in audit.SYMBOLS for t in audit.PERIOD_COUNTS]

def test_duplicate_missing_source_and_unsafe_rows_rejected():
    rows = records()
    assert watch.validate_records(rows, audit.SYMBOLS, audit.PERIOD_COUNTS)
    assert not watch.validate_records(rows[:-1], audit.SYMBOLS, audit.PERIOD_COUNTS)
    assert not watch.validate_records(rows+[rows[0]], audit.SYMBOLS, audit.PERIOD_COUNTS)
    for field,value in (("data_source","tencent"),("live_trade",True),("invalid_grid_rows",1)):
        bad = [dict(r) for r in rows]
        bad[0][field] = value
        assert not watch.validate_records(bad, audit.SYMBOLS, audit.PERIOD_COUNTS)

def test_weekend_skips_child_and_credentials(monkeypatch,tmp_path):
    monkeypatch.setattr(watch.subprocess,"run",lambda *a,**k: pytest.fail("provider child called"))
    result = watch.run_once(tmp_path, now=datetime(2026,10,24,2,tzinfo=timezone.utc), execute=True)
    assert result["status"] == "NOT_OBSERVED"
    assert result["provider_requests"] == 0

def test_drift_prevents_child(monkeypatch,tmp_path):
    root = deployed(tmp_path)
    (root/"audit_tickflow_windows_readonly.py").write_text("# stale deployment")
    monkeypatch.setattr(watch,"session_window",lambda n:"SESSION_OBSERVATION_WINDOW")
    monkeypatch.setattr(watch.subprocess,"run",lambda *a,**k: pytest.fail("provider child called"))
    assert watch.run_once(root,execute=True)["status"] == "DEPLOYMENT_DRIFT_BLOCKED"

def test_timeout_invalidates_previous_pass_and_restart_revalidates(monkeypatch,tmp_path):
    root = deployed(tmp_path)
    monkeypatch.setattr(watch,"session_window",lambda n:"SESSION_OBSERVATION_WINDOW")
    def timeout(*args,**kwargs):
        assert kwargs["timeout"] == 190
        raise subprocess.TimeoutExpired("private-secret",190,stderr="PRIVATE_KEY")
    monkeypatch.setattr(watch.subprocess,"run",timeout)
    blocked = watch.run_once(root,execute=True)
    assert blocked["status"] == "CHILD_TIMEOUT_BLOCKED"
    assert "PRIVATE_KEY" not in json.dumps(watch.load_state(root/"latest-poll.json"))
    monkeypatch.setitem(__import__("sys").modules,"audit_tickflow_windows_readonly",audit)
    monkeypatch.setattr(watch.subprocess,"run",lambda *a,**k: SimpleNamespace(
        returncode=0, stdout="\n".join(json.dumps(r) for r in records())))
    recovered = watch.run_once(root,execute=True)
    assert recovered["sequence"] == blocked["sequence"]+1
    assert recovered["status"] == "PASS_SESSION_RESEARCH_ONLY"
    assert recovered["live_trade"] is False
    assert recovered["production_acceptance"] == "NOT_VERIFIED"

def test_label_regression_is_not_new_data():
    before = records()
    after = records()
    after[0]["data_time_utc"] = "2026-10-23T01:00:00+00:00"
    assert watch.compare_records(before,after)["latest_label_regressions"] == 1

def test_interrupted_atomic_publication_preserves_prior_receipt(monkeypatch,tmp_path):
    path = tmp_path/"state.json"
    watch.atomic_write(path,{"sequence":1})
    monkeypatch.setattr(watch.os,"replace",lambda *a: (_ for _ in ()).throw(OSError("fail")))
    with pytest.raises(OSError):
        watch.atomic_write(path,{"sequence":2})
    assert watch.load_state(path) == {"sequence":1}
    assert list(tmp_path.iterdir()) == [path]

def test_successor_must_be_immediate_same_day_grid():
    values = frame()
    values["timestamp"].pop(1)
    for key in ("open","high","low","close","volume"):
        values[key].pop(1)
    out = audit.frame_receipt(values,"15m",datetime.fromisoformat("2026-10-23T10:32:00+08:00"))
    assert out["row_receipts"][0]["operational_closed"] is False
    assert out["row_receipts"][1]["operational_closed"] is True
    assert out["row_receipts"][-1]["operational_closed"] is False

def test_calendar_unknown_fails_closed_without_child(monkeypatch,tmp_path):
    monkeypatch.setattr(watch,"session_window",lambda now:"CALENDAR_UNVERIFIED")
    monkeypatch.setattr(watch.subprocess,"run",lambda *a,**k: pytest.fail("provider child called"))
    assert watch.run_once(tmp_path,execute=True)["status"] == "NOT_OBSERVED"

def test_new_process_reuses_persisted_sequence_but_never_reuses_quality(monkeypatch,tmp_path):
    root = deployed(tmp_path)
    monkeypatch.setattr(watch,"session_window",lambda n:"SESSION_OBSERVATION_WINDOW")
    monkeypatch.setitem(__import__("sys").modules,"audit_tickflow_windows_readonly",audit)
    monkeypatch.setattr(watch.subprocess,"run",lambda *a,**k: SimpleNamespace(
        returncode=0,stdout="\n".join(json.dumps(r) for r in records())))
    assert watch.run_once(root,execute=True)["status"] == "PASS_SESSION_RESEARCH_ONLY"
    monkeypatch.setattr(watch.subprocess,"run",lambda *a,**k: SimpleNamespace(returncode=1,stdout=""))
    second = watch.run_once(root,execute=True)
    assert second["sequence"] == 2
    assert second["status"] == "DATA_QUALITY_BLOCKED"
    assert watch.load_state(root/"latest-poll.json")["status"] == "DATA_QUALITY_BLOCKED"
