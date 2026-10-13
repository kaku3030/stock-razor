"""Public GitHub Actions must not print AWS SSM service credentials or raw logs."""

from pathlib import Path

import yaml


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/aws-ssm-ops.yml"
)


def test_workflow_has_fixed_ssm_actions_and_credentials_not_persisted():
    text = WORKFLOW.read_text(encoding="utf-8")
    config = yaml.safe_load(text)
    assert config["jobs"]["read-only-ssm"]["steps"][-1]["name"] == "Wait for SSM result"
    assert "id-token: write" in text
    assert "aws-actions/configure-aws-credentials@v4" in text


def test_service_diagnostic_is_redacted():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    action = workflow.split("us_livefeed_runtime_diff_audit)", 1)[1].split(";;", 1)[0]
    assert 'LIVEFEED_PROCESS_METADATA_REDACTED=YES' in action
    assert 'LIVEFEED_PROCESS_PRESENT=YES' in action
    assert 'ProtectSystem --no-pager' in action


def test_ssm_status_projection_never_prints_remote_stdout_or_stderr():
    text = WORKFLOW.read_text(encoding="utf-8")
    # Even after removing the explicit environ probe, other diagnostics may
    # accidentally print secrets. Never forward raw SSM output to the PUBLIC
    # Actions runner log on success OR failure.
    assert text.count("--query '{Status:Status,ResponseCode:ResponseCode}'") == 1
    assert "StandardOutputContent --output text" in text
    assert "StandardErrorContent:StandardErrorContent" not in text

    config = yaml.safe_load(text)
    steps = config["jobs"]["read-only-ssm"]["steps"]
    wait_step = next(item for item in steps if item["name"] == "Wait for SSM result")
    script = wait_step["run"]
    assert "StandardOutputContent --output text" in script
    assert "StandardErrorContent" not in script
    assert script.count("--query '{Status:Status,ResponseCode:ResponseCode}'") == 1
    assert "sanitize_ssm_probe_output.py" in script
    assert "Status" in script
    assert "ResponseCode" in script


def test_no_auto_deploy_or_broker_permission_added():
    config = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "workflow_dispatch" in config.get("on", config.get(True, {}))
    assert "push" not in config.get("on", config.get(True, {}))
    assert config["permissions"] == {"id-token": "write", "contents": "read"}
