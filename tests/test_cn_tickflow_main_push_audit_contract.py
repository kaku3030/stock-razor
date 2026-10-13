"""Regression guard: triggering an AWS TickFlow read-only audit on protected main changes."""
from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/audit-cn-tickflow-live-research.yml"
)


def test_audit_push_event_is_exact_main_and_path_scoped():
    s = WORKFLOW.read_text(encoding="utf-8")
    assert (
        "  push:\n"
        "    branches: [main]\n"
        "    paths:\n"
        "      - 'scripts/audit_cn_tickflow_research_runtime.py'\n"
        "      - '.github/workflows/audit-cn-tickflow-live-research.yml'\n"
    ) in s
    assert "  workflow_dispatch:" in s
    assert "  schedule:" in s
    assert "if: github.ref == 'refs/heads/main'" in s


def test_audit_does_not_change_paid_worker_or_trading_gates():
    s = WORKFLOW.read_text(encoding="utf-8")
    assert "Verify two isolated AWS snapshots 65 seconds apart" in s
    assert 'assert d.get("source_arbiter_admission")=="BLOCKED"' in s
    assert 'assert d.get("radar_admission")=="BLOCKED"' in s
    assert 'assert d.get("live_trade")=="NO"' in s
    assert 'assert d.get("canonical_write")=="NO"' in s
    assert "approve_paid_tickflow_ingestion" not in s
