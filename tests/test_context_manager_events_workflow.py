from pathlib import Path


WORKFLOW = Path(".github/workflows/context-manager-events.yml").read_text(encoding="utf-8")


def test_context_event_workflow_is_owner_bound_and_exact_main_guarded():
    assert '"on":' in WORKFLOW
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
    assert "RECORDED|DUPLICATE" in WORKFLOW
    assert "CONTEXT_MANAGER_EVENT_SYNC=" in WORKFLOW
