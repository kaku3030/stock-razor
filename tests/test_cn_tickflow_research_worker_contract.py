from datetime import datetime,timezone
from scripts.run_cn_tickflow_research_worker import _interval

def test_live_cn_session_poll_and_failure_rate_limit():
    assert _interval(datetime(2026,10,13,2,10,tzinfo=timezone.utc))==60
    assert _interval(datetime(2026,10,13,5,10,tzinfo=timezone.utc))==60
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

