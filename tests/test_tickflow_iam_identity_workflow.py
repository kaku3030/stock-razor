from pathlib import Path


WORKFLOW = Path(".github/workflows/audit-tickflow-iam-identity.yml").read_text(encoding="utf-8")


def test_tickflow_iam_audit_is_dispatch_only_read_only_and_secrets_free():
    assert "workflow_dispatch:" in WORKFLOW
    assert "push:" not in WORKFLOW
    assert "pull_request:" not in WORKFLOW
    assert "role-to-assume: arn:aws:iam::888425712426:role/StockRazorGitHubOpsRole" in WORKFLOW
    assert "aws iam get-instance-profile" in WORKFLOW
    assert "aws ec2 describe-instances" in WORKFLOW
    assert "aws ssm send-command" in WORKFLOW
    assert "X-aws-ec2-metadata-token-ttl-seconds: 30" in WORKFLOW
    assert "/latest/meta-data/iam/security-credentials/ " in WORKFLOW
    assert "TICKFLOW_IAM_REMOTE_ROLE=(EXPECTED|IMDS_UNAVAILABLE|OTHER)" in WORKFLOW
    assert "LIVE_TRADE=NO" in WORKFLOW
    assert "RADAR_ADMISSION=BLOCKED" in WORKFLOW
    for forbidden in (
        "get-secret-value", "SecretString", "kms:Decrypt", "aws iam put-",
        "aws iam attach-", "aws iam create-", "aws iam delete-",
        "aws secretsmanager get-", "aws secretsmanager put-", "aws secretsmanager update-",
        "printenv", "/proc/self/environ",
    ):
        assert forbidden not in WORKFLOW
