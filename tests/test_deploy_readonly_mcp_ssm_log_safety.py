"""A PUBLIC GitHub Actions deployment log must never mirror SSM payloads."""

from pathlib import Path

import yaml
import pytest
import subprocess


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


def test_mcp_deploy_is_owner_only_and_auto_triggers_on_bounded_main_runtime_changes():
    text = WORKFLOW.read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    triggers = document.get("on", document.get(True, {}))
    assert "workflow_dispatch" in triggers
    assert "pull_request" not in triggers
    assert triggers["push"]["branches"] == ["main"]
    # Never restart production read-only MCP for an unrelated GitHub PR,
    # docs-only change, trading-code edit, or even generic main merge.
    assert set(triggers["push"]["paths"]) == {
        ".github/workflows/deploy-readonly-mcp.yml",
        "ops/aws/install_readonly_mcp.sh",
        "realtime_monitor/readonly_mcp_server.py",
        "src/services/context_manager.py",
        "scripts/record_context_event.py",
    }
    assert document["permissions"] == {"id-token": "write", "contents": "read"}
    assert "github.ref == 'refs/heads/main' && github.actor == github.repository_owner" in text
    steps = document["jobs"]["deploy"]["steps"]
    assert next(s for s in steps if s.get("id") == "deploy")
    assert "MCP_DEPLOY_MAIN_MOVED_ABORT" in text
    assert "MCP_DEPLOY_PRE_SSM_MAIN_MOVED_ABORT" in text
    assert "TARGET_INSTANCE_ID: i-01738342af3efac72" in text
    assert "aws ssm send-command" in text
    assert "git rev-parse HEAD" in text
    assert "trade:write" not in text


@pytest.mark.parametrize("error,expected", [
    ("ContextManagerError: event log version sequence is invalid", "CONTEXT_EVENT_SEQUENCE_INVALID"),
    ("ContextManagerError: event log integrity check failed", "CONTEXT_EVENT_INTEGRITY_INVALID"),
    ("ContextManagerError: event log fields are invalid", "CONTEXT_EVENT_SCHEMA_INVALID"),
    ("ModuleNotFoundError: private-module", "PYTHON_DEPENDENCY_MISSING"),
    ("PermissionError: private-path", "FILE_PERMISSION_BLOCKED"),
    ("unknown provider error", "UNCLASSIFIED"),
])
def test_remote_install_failure_publishes_only_fixed_diagnosis(tmp_path, error, expected):
    document = yaml.safe_load(WORKFLOW.read_text())
    script = next(s["run"] for s in document["jobs"]["deploy"]["steps"] if s.get("id") == "deploy")
    block = script.split("diagnosis=UNCLASSIFIED", 1)[1].split("echo 'READONLY_MCP_INSTALL=BLOCKED'", 1)[0]
    # Reproduce the one unquoted-heredoc expansion before execution on EC2.
    block = ("diagnosis=UNCLASSIFIED" + block).replace("\\$", "$")
    (tmp_path / "install.err").write_text("private-host secret-value\n" + error)
    result = subprocess.run(["bash", "-eu", "-c", 'stage="$1"\n' + block, "probe", str(tmp_path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert result.stdout.strip() == "READONLY_MCP_INSTALL_FAILURE=" + expected
    assert "secret-value" not in result.stdout + result.stderr


@pytest.mark.parametrize("remote,expected", [
    ("private-host secret-value\nREADONLY_MCP_INSTALL_FAILURE=CONTEXT_EVENT_SEQUENCE_INVALID\n", "CONTEXT_EVENT_SEQUENCE_INVALID"),
    ("READONLY_MCP_INSTALL_FAILURE=private-host secret-value\n", "UNCLASSIFIED"),
])
def test_runner_failure_output_rejects_non_allowlisted_remote_content(remote, expected):
    script = _wait_script().split('if [ "$status" != "Success" ]; then', 1)[1].split("exit 1", 1)[0]
    prelude = 'aws(){ printf "%s" "$REMOTE_CONTENT"; }; export -f aws\nCOMMAND_ID=fixture\nTARGET_INSTANCE_ID=fixture\n'
    import os
    result = subprocess.run(["bash", "-eu", "-c", prelude + script], env={**os.environ, "REMOTE_CONTENT": remote}, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "READONLY_MCP_INSTALL_FAILURE=" + expected in result.stdout
    assert "secret-value" not in result.stdout + result.stderr
