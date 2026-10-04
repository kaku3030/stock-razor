from pathlib import Path

WORKFLOW = Path(".github/workflows/deploy-futures-runtime.yml").read_text()


def test_manual_oidc_ssm_deploy_is_fixed_and_read_only():
    assert "workflow_dispatch:" in WORKFLOW
    assert "id-token: write" in WORKFLOW
    assert "StockRazorGitHubOpsRole" in WORKFLOW
    assert "environment:" not in WORKFLOW
    assert "ap-northeast-1" in WORKFLOW
    assert "i-01738342af3efac72" in WORKFLOW
    assert "AWS-RunShellScript" in WORKFLOW
    assert "install_futures_runtime.sh" in WORKFLOW


def test_runtime_evidence_never_promotes_cloud_or_trade():
    assert "FUTURES_AWS_RUNTIME_DEPLOYMENT=PASS" in WORKFLOW
    assert "CLOUD_RUNTIME=NOT_VERIFIED" in WORKFLOW
    assert "PC_OFF_INDEPENDENCE=NOT_VERIFIED" in WORKFLOW
    assert "LIVE_TRADE=NO" in WORKFLOW
    assert '"live_trade":false' in WORKFLOW


def test_workflow_does_not_use_static_aws_credentials():
    assert "aws-access-key-id" not in WORKFLOW
    assert "aws-secret-access-key" not in WORKFLOW
