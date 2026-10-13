from pathlib import Path


WORKFLOW = Path(".github/workflows/context-manager-events.yml").read_text(encoding="utf-8")


def test_context_event_workflow_is_owner_bound_and_exact_main_guarded():
    assert '"on":' in WORKFLOW
    assert 'workflows: [CI, "Research Radar Tests"]' in WORKFLOW
    assert "  push:" in WORKFLOW
    assert "  pull_request:" not in WORKFLOW
    assert "github.event_name == 'push' || github.event_name == 'workflow_run'" in WORKFLOW
    assert "github.repository_owner == 'kaku3030'" in WORKFLOW
    assert "test \"$GITHUB_ACTOR\" = 'kaku3030'" in WORKFLOW
    assert "test \"$main_head\" = \"$(git rev-parse HEAD)\"" in WORKFLOW
    assert "test \"$main_head\" = \"$GITHUB_SHA\"" in WORKFLOW
    assert "TARGET_INSTANCE_ID: i-01738342af3efac72" in WORKFLOW
    assert "arn:aws:iam::888425712426:role/StockRazorGitHubOpsRole" in WORKFLOW


def test_context_event_workflow_uses_allowlisted_payload_and_redacted_result():
    assert "jq -cn --arg" in WORKFLOW
    assert "SecretString" not in WORKFLOW
    assert "StandardOutputContent" in WORKFLOW
    assert '.status == "RECORDED" or .status == "DUPLICATE"' in WORKFLOW
    assert "CONTEXT_MANAGER_EVENT_SYNC=PASS" in WORKFLOW
    assert "CONTEXT_MANAGER_PR_SYNC=PASS" in WORKFLOW
    assert "grep -Eq" not in WORKFLOW
    assert "CONTEXT_MANAGER_EVENT_SYNC=" in WORKFLOW
    assert "commits/$GITHUB_SHA/pulls" in WORKFLOW
    assert "CONTEXT_MANAGER_PR_SYNC=" in WORKFLOW
    assert "GH_TOKEN: ${{ github.token }}" in WORKFLOW

def test_context_event_ssm_command_never_relies_on_escaped_multiline_flags():
    import yaml
    workflow = yaml.safe_load(WORKFLOW)
    script = next(step["run"] for step in workflow["jobs"]["sync"]["steps"] if step.get("name") == "Record allowlisted event over SSM")
    assert script.count('remote="$(printf') == 2
    assert script.count('"set -eu"') == 2  # AWS SSM runs /bin/sh, not bash
    # Only single-line command invocation; no nested heredocs or line splitting.
    invocation_lines = [line for line in script.splitlines() if "record_context_event.py" in line]
    assert len(invocation_lines) == 2
    assert all("--event-id" in line and "--source-ref" in line and "--payload-json" in line for line in invocation_lines)
    assert all(" --ttl-seconds 604800" in line for line in invocation_lines)
    assert 'echo "CONTEXT_MANAGER_EVENT_SYNC=PASS"' in script
    assert 'echo "CONTEXT_MANAGER_PR_SYNC=PASS"' in script

def test_context_event_status_parser_respects_sorted_json_and_fails_closed():
    import json
    import shutil
    import subprocess
    import pytest

    if shutil.which("jq") is None:
        pytest.skip("jq is present on GitHub Linux runners, unavailable here")
    expr = '.status == "RECORDED" or .status == "DUPLICATE"'
    for status, allowed in (("RECORDED", True), ("DUPLICATE", True),
                            ("BLOCKED", False), ("FAILED", False)):
        # record_context_event.py explicitly emits sorted JSON keys.
        result = json.dumps({"status": status, "event_id": "example", "version": 1},
                            sort_keys=True)
        completed = subprocess.run(["jq", "-e", expr], input=result, text=True,
                                   capture_output=True, check=False)
        assert (completed.returncode == 0) is allowed
    malformed = subprocess.run(["jq", "-e", expr], input="{bad", text=True,
                               capture_output=True, check=False)
    assert malformed.returncode != 0
