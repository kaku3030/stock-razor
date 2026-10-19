from datetime import datetime,timezone
from scripts.run_cn_tickflow_research_worker import _interval

def test_live_cn_session_poll_and_failure_rate_limit():
    assert _interval(datetime(2026,10,13,2,10,tzinfo=timezone.utc))==15
    assert _interval(datetime(2026,10,13,5,10,tzinfo=timezone.utc))==15
    assert _interval(datetime(2026,10,13,4,10,tzinfo=timezone.utc))==300
    assert _interval(datetime(2026,10,13,2,10,tzinfo=timezone.utc),failure=True)==300
    assert _interval(datetime(2026,10,18,2,10,tzinfo=timezone.utc))==900

def test_paid_research_worker_is_explicitly_separate_from_trade_writer():
    from pathlib import Path
    root=Path(__file__).parent.parent
    worker=(root/"scripts/run_cn_tickflow_research_worker.py").read_text(encoding='utf-8')
    install=(root/"ops/aws/install_cn_tickflow_research.sh").read_text(encoding='utf-8')
    workflow=(root/".github/workflows/deploy-cn-tickflow-research.yml").read_text(encoding='utf-8')
    assert 'stock-razor-cn-tickflow-research.service' in install
    assert 'canonical_write_authorized' in worker
    assert 'approved_paid_tickflow' not in workflow  # only opt-in named below
    assert "approve_paid_tickflow_ingestion" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "SOURCE_ARBITER_ADMISSION=BLOCKED" in install
    assert "max_retries=0" in worker
    assert "RestartSec=180" in install
    assert "StartLimitBurst=4" in install
    assert "LIVE_TRADE=NO" in workflow
    assert "REPO_REF" in install and "repo_sha" not in workflow


def test_normalizer_diagnostic_is_fixed_enum_and_never_raw_payload():
    from scripts.run_cn_tickflow_research_worker import _normalize_rejection_reason
    known=ValueError("unexpected Shanghai regular-session grid")
    known._tickflow_stage="S0_15M_NORMALIZE"
    assert _normalize_rejection_reason(known)=="HISTORICAL_SESSION_GRID_MISMATCH"
    private=ValueError("actual-secret=private and provider payload")
    private._tickflow_stage="S0_15M_NORMALIZE"
    assert _normalize_rejection_reason(private)=="OTHER"
    private._tickflow_stage="S0_15M_FETCH"
    assert _normalize_rejection_reason(private)=="NOT_APPLICABLE"
    assert _normalize_rejection_reason(TypeError("secret"))=="NOT_APPLICABLE"


def test_network_poll_recovery_is_bounded_and_preserves_permanent_failure_backoff():
    from scripts.run_cn_tickflow_research_worker import _network_retry_interval
    now = datetime(2026,10,15,9,0,tzinfo=timezone.utc)  # after CN close
    error = TimeoutError("private provider detail")
    assert [_network_retry_interval(now,error,n) for n in range(1,9)] == [15,30,60,120,240,300,300,300]
    for error in (ValueError("bad rows"), RuntimeError("auth"),
                  type("RateLimitError",(Exception,),{})("429")):
        assert _network_retry_interval(now,error,1) == 300
    assert _network_retry_interval(datetime(2026,10,18,9,0,tzinfo=timezone.utc),TimeoutError(),1)==900
    assert _network_retry_interval(now,TimeoutError(),10**10)==300
    assert _network_retry_interval(now,None,0)==300


def test_poll_loop_resets_network_backoff_after_success_and_closes_sdk(monkeypatch):
    import sys
    from types import SimpleNamespace
    import scripts.run_cn_tickflow_research_worker as worker
    elapsed = [0]
    attempts = []
    published = []
    closed = []
    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0
        def close(self):
            closed.append(True)
    def observe(*args, **kwargs):
        attempts.append(elapsed[0])
        if len(attempts) in (1,2,4):
            raise TimeoutError("private network detail")
        if len(attempts) == 5:
            worker.running = False
        return {"status":"PASS_RESEARCH_ONLY"}
    class FixedDateTime:
        @staticmethod
        def now(tz):
            return datetime(2026,10,15,9,0,tzinfo=timezone.utc)
    monkeypatch.setenv("STOCK_RAZOR_REPO_SHA", "a" * 40)
    monkeypatch.setattr(worker, "running", True)
    monkeypatch.setattr(worker, "datetime", FixedDateTime)
    monkeypatch.setattr(worker, "_credential", lambda: "in-memory-fixture")
    monkeypatch.setattr(worker.signal, "signal", lambda *a: None)
    monkeypatch.setitem(sys.modules, "tickflow", SimpleNamespace(TickFlow=FakeClient))
    monkeypatch.setattr(worker, "build_observation", observe)
    monkeypatch.setattr(worker, "atomic_publish", lambda path,payload: published.append(payload))
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: elapsed.__setitem__(0,elapsed[0]+seconds))
    assert worker.main() == 0
    assert attempts == [0,15,45,345,360]
    assert [p["status"] for p in published] == ["BLOCKED","BLOCKED","PASS_RESEARCH_ONLY","BLOCKED","PASS_RESEARCH_ONLY"]
    assert all(p["radar_admission"]=="BLOCKED" and not p["live_trade"] for p in published if p["status"]=="BLOCKED")
    assert closed == [True]


def test_private_batch_error_message_is_never_projected_as_reason():
    from scripts.run_cn_tickflow_research_worker import _normalize_rejection_reason

    error = ValueError("api_key=DO_NOT_ECHO provider body")
    error._tickflow_stage = "BATCH_1M_FETCH"
    assert _normalize_rejection_reason(error) == "NOT_APPLICABLE"


def test_row_count_failure_diagnostics_are_split_without_provider_counts():
    from scripts.run_cn_tickflow_research_worker import _normalize_rejection_reason
    below=ValueError("insufficient history")
    below._tickflow_stage="S0_60M_NORMALIZE"
    above=ValueError("history exceeds configured bound")
    above._tickflow_stage="S0_60M_NORMALIZE"
    assert _normalize_rejection_reason(below)=="ROW_COUNT_BELOW_MIN"
    assert _normalize_rejection_reason(above)=="ROW_COUNT_ABOVE_MAX"
    legacy=ValueError("insufficient or unbounded history")
    legacy._tickflow_stage="S0_60M_NORMALIZE"
    assert _normalize_rejection_reason(legacy)=="ROW_COUNT_OUT_OF_BOUNDS"
