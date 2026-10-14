"""Contract guards for the read-only Paper SSM qualification workflow."""

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/qualify-paper-runtime-ssm-readonly.yml"


def test_workflow_is_fixed_target_oidc_and_closed_by_default():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "id-token: write" in text
    assert "contents: read" in text
    assert "role-to-assume: arn:aws:iam::888425712426:role/StockRazorGitHubOpsRole" in text
    assert 'TARGET_INSTANCE_ID: i-01738342af3efac72' in text
    assert 'PAPER_AUTO_READY: "NO"' in text
    assert "RADAR_ADMISSION: BLOCKED" in text
    assert "SOURCE_ARBITER_ADMISSION: BLOCKED" in text
    assert 'LIVE_TRADE: "NO"' in text
    assert 'TRADE_EXECUTION: "NO"' in text


def test_workflow_has_no_mutation_or_order_capability():
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "systemctl start", "systemctl stop", "systemctl restart",
        "aws-actions/configure-aws-credentials@",  # checked separately below
        "GetSecretValue", "broker.place", "create_paper_adapter",
        "paper-order-", "provider.connect", "OpenD",
    ):
        if forbidden == "aws-actions/configure-aws-credentials@":
            continue
        assert forbidden not in text
    assert "aws ssm send-command" in text
    assert "SSM_PROBE_ORDER_ACTIONS NONE" in text
    assert "PAPER_EXTERNAL_TRADING_ACTIVITY NOT_VERIFIED" in text
    assert "grep -E '^(PAPER_|SSM_PROBE_|RAW_RUNTIME_)'" in text
    assert "PAPER_EXTERNAL_BROKER_ORDERS" not in text
    assert "PAPER_SIMULATED_ORDERS" not in text
    assert "PAPER_RESTART_RECOVERY UNVERIFIED" in text


def test_schedule_probe_uses_controlled_config_without_process_environment():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "/proc/" not in text
    assert "environ" not in text
    assert 'systemctl show "$unit" -p ExecStart --value' in text
    assert '"$working/.env"' in text
    assert "SCHEDULE_TIMES" in text
    assert "PAPER_HALF_HOUR_SCHEDULE UNKNOWN" in text


def test_order_activity_is_not_claimed_from_a_read_only_probe():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "runtime orders were not inspected" in text
    assert "PAPER_EXTERNAL_TRADING_ACTIVITY=(YES|true|PASS)" in text
    assert "External trading activity: NOT_VERIFIED" in text


def test_workflow_withholds_raw_runtime_output_and_checks_exact_main():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "persist-credentials: false" in text
    assert "git rev-parse HEAD" in text
    assert "git/ref/heads/main" in text
    assert "PAPER_RUNTIME_SHA PASS" in text
    assert "EXPECTED_RUNTIME_SHA_PLACEHOLDER" in text
    assert "RAW_RUNTIME_OUTPUT_WITHHELD YES" in text
    assert "SecretString: NOT_READ" in text
