from pathlib import Path


WORKFLOW = Path(
    ".github/workflows/audit-tickflow-aws-inventory-readonly.yml"
).read_text(encoding="utf-8")


def test_inventory_workflow_is_oidc_pinned_and_read_only():
    assert "workflow_dispatch:" in WORKFLOW
    assert "id-token: write" in WORKFLOW
    assert "contents: read" in WORKFLOW
    assert "ref: ${{ github.sha }}" in WORKFLOW
    assert "git rev-parse HEAD" in WORKFLOW
    assert "git/ref/heads/main" in WORKFLOW
    assert "configure-aws-credentials@v4" in WORKFLOW
    assert "AWS-RunShellScript" in WORKFLOW
    assert "AWS_INVENTORY_SCOPE=READ_ONLY" in WORKFLOW
    assert "AWS_INVENTORY_SECRETS=NOT_READ" in WORKFLOW
    assert "RADAR_ADMISSION=BLOCKED" in WORKFLOW
    assert "PAPER_AUTO_READY=NO" in WORKFLOW
    assert "LIVE_TRADE=NO" in WORKFLOW


def test_inventory_workflow_has_no_mutation_or_secret_ingress():
    forbidden = (
        "systemctl restart",
        "systemctl stop",
        "systemctl start",
        "apt-get",
        "pip install",
        "SecretString",
        "get-secret-value",
        "get-parameter",
        "WithDecryption",
    )
    assert not any(item in WORKFLOW for item in forbidden)
    assert "SERVICE_MUTATIONS=NONE" in WORKFLOW


def test_inventory_covers_target_identity_runtime_services_and_cost_blocker():
    for marker in (
        "EC2_METADATA=",
        "EC2_PLATFORM=",
        "EC2_TAG_SERVICE=",
        "SSM_PLATFORM_NAME=",
        "classify OPEND",
        "classify MCP",
        "classify CN_WORKER",
        "COST_EXPLORER=",
        "COST_TOTAL_USD_BUCKET=",
        "COST_EXPLORER_ACCESS=DENIED_OR_UNAVAILABLE",
    ):
        assert marker in WORKFLOW


def test_inventory_does_not_echo_raw_aws_payloads_or_account_identity():
    assert "aws sts get-caller-identity" not in WORKFLOW
    assert "StandardErrorContent" not in WORKFLOW
    assert "echo \"$instance_json\"" not in WORKFLOW
    assert "echo \"$ssm_json\"" not in WORKFLOW


def test_inventory_rechecks_main_before_ssm_command():
    guard = WORKFLOW.index("INVENTORY_MAIN_MOVED_ABORT")
    command = WORKFLOW.index("aws ssm send-command")
    assert guard < command
    assert "GH_TOKEN: ${{ github.token }}" in WORKFLOW
