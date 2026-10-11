"""A PUBLIC GitHub Actions deployment log must never mirror SSM payloads."""

from pathlib import Path

import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/deploy-readonly-mcp.yml"


def _wait_script() -> str:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = document["jobs"]["deploy"]["steps"]
    return next(s["run"] for s in steps if s.get("name") == "Wait and collect deployment evidence")


def test_mcp_ssm_wait_step_has_no_raw_stdout_or_stderr_in_public_logs():
    script = _wait_script()
    assert "StandardOutputContent:StandardOutputContent" not in script
    assert "StandardErrorContent:StandardErrorContent" not in script
    assert "list-command-invocations" not in script
    assert "printf '%s\\n' \"$invocation\"" not in script
    assert "SSM_REMOTE_OUTPUT_GITHUB_LOG=WITHHELD" in script
    assert "SSM_DETAILS_REQUIRE_PRIVATE_AWS_ACCESS=YES" in script


def test_mcp_ssm_reads_service_active_proof_without_echoing_raw_payload():
    script = _wait_script()
    assert "--query '{Status:Status,ResponseCode:ResponseCode,ExecutionElapsedTime:ExecutionElapsedTime}'" in script
    assert "--query StandardOutputContent --output text" in script
    assert "grep -Fxq 'active'" in script
    assert 'READONLY_MCP_EVIDENCE_MISSING=SERVICE_ACTIVE' in script
    assert 'READONLY_MCP_AWS_DEPLOYMENT=PASS' in script
    assert 'LIVE_TRADE=NO' in script


def test_mcp_deploy_remains_manual_and_fixed_to_existing_ssm_target():
    text = WORKFLOW.read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    triggers = document.get("on", document.get(True, {}))
    assert "workflow_dispatch" in triggers
    assert "push" not in triggers
    assert document["permissions"] == {"id-token": "write", "contents": "read"}
    steps = document["jobs"]["deploy"]["steps"]
    assert next(s for s in steps if s.get("id") == "deploy")
    assert "aws ssm send-command" in text
    assert "git rev-parse HEAD" in text
    assert "trade:write" not in text
