"""Contract guard for the manually-dispatched, offline-only Paper CI lane."""

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/paper-offline-no-orders.yml"


def test_offline_paper_workflow_has_no_external_execution_capabilities():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "schedule:" not in text
    assert "permissions:\n  contents: read" in text
    for disallowed in (
        "aws-actions/", "id-token: write", "secrets.",
        "aws ssm", "aws ec2", "GetSecretValue", "OpenD",
        "broker.place", "LIVE_TRADE: \"YES\"",
    ):
        # Comments mentioning provider names are harmless; protect executable
        # syntax separately below rather than banning documentation comments.
        if disallowed in ("OpenD",):
            continue
        assert disallowed not in text
    assert "persist-credentials: false" in text
    assert "LIVE_TRADE: \"NO\"" in text
    assert "TRADE_EXECUTION: \"NO\"" in text
    assert "PAPER_AUTO_READY: \"NO\"" in text
    assert "RADAR_ADMISSION: BLOCKED" in text
    assert "SOURCE_ARBITER_ADMISSION: BLOCKED" in text


def test_paper_ci_runs_real_deterministic_recovery_and_no_order_tests():
    text = WORKFLOW.read_text(encoding="utf-8")
    for test_file in (
        "test_offline_paper_simulation.py",
        "test_paper_runtime_orchestrator.py",
        "test_paper_process_soak.py",
        "test_paper_multisession_soak.py",
        "test_paper_cloud_evidence_review.py",
        "test_sim_account_continuity.py",
        "test_verify_sim_cross_host_private.py",
    ):
        assert f"tests/{test_file}" in text
    assert "Cloud broker/SIM account or independent fills: NOT_TESTED" in text
    assert "Cloud live market data/15m/60m closure: NOT_TESTED" in text
    assert "- Paper external orders: NONE" in text

def test_offline_paper_acceptance_runs_on_protected_main_changes_without_pc():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text  # independent manual replay preserved
    assert "  push:\n    branches: [main]" in text
    assert '"src/services/paper_*.py"' in text
    assert '"tests/test_paper_*.py"' in text
    assert '".github/workflows/paper-offline-no-orders.yml"' in text
    assert "  pull_request:" not in text
    assert "  schedule:" not in text
    assert "runs-on: ubuntu-latest" in text
    assert "permissions:\n  contents: read" in text
    assert "id-token: write" not in text
    assert "aws-actions/" not in text
    assert "PAPER_AUTO_READY: \"NO\"" in text
    assert "TRADE_EXECUTION: \"NO\"" in text
