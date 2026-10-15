"""Static fail-closed contract checks for manual EC2 Hub audit workflow."""
from pathlib import Path

WORKFLOW = Path(".github/workflows/audit-feedback-hub-ec2-readonly.yml")


def test_owner_main_only_and_default_off():
    code = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in code
    assert "default: false" in code
    assert "github.actor == github.repository_owner" in code
    assert "test \"$GITHUB_REF\" = refs/heads/main" in code
    assert "test \"$(git rev-parse HEAD)\" = \"$GITHUB_SHA\"" in code
    assert "current_main=" in code
    assert "test \"$current_main\" = \"$GITHUB_SHA\"" in code
    assert "schedule:" not in code
    assert "issue_comment:" not in code
    assert "pull_request:" not in code


def test_read_only_probe_does_not_claim_persistence():
    code = WORKFLOW.read_text(encoding="utf-8")
    assert "audit_feedback_hub_ec2_readonly.py" in code
    assert "sha256sum -c -" in code
    assert "mode=ro" in Path(
        "scripts/audit_feedback_hub_ec2_readonly.py"
    ).read_text(encoding="utf-8")
    assert "FEEDBACK_HUB_CROSS_RUN_PERSISTENCE=NOT_VERIFIED" in code
    assert "FEEDBACK_HUB_PRODUCERS=NOT_VERIFIED" in code
    assert "TRADING_AUTHORITY=NO" in code
    assert "ssm send-command" in code
    assert "role-to-assume:" in code
    assert "vars.STOCK_RAZOR_GITHUB_OPS_ROLE_ARN" in code
    assert "aws iam " not in code
    assert "aws secretsmanager " not in code
    assert "aws ec2 stop-instances" not in code
    assert "aws ec2 start-instances" not in code
    assert "git push" not in code
    assert "gh pr merge" not in code
