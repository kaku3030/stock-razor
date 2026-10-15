import json
from pathlib import Path

import pytest

from engineering_autonomy.deepseek_probe import REQUEST, classify_status, validate_completion


def test_probe_is_exactly_one_nonstreaming_cheap_supported_model():
    assert REQUEST["model"] == "deepseek-flash"
    assert REQUEST["stream"] is False
    assert REQUEST["thinking"] == {"type": "disabled"}
    assert REQUEST["max_tokens"] <= 24
    assert len(REQUEST["messages"]) == 1


def test_completion_structural_validation():
    validate_completion(json.dumps({
        "id": "sample-id",
        "choices": [{"message": {"role": "assistant", "content": "OK"}}]
    }).encode("utf-8"))


@pytest.mark.parametrize("body", [
    b"", b"{}", b'{"id":"x","choices":[]}',
    b'{"id":"x","choices":[{"message":{"content":""}}]}',
    b"invalid json", b"x" * 65537,
])
def test_probe_malformed_response_rejected(body):
    with pytest.raises(ValueError):
        validate_completion(body)


@pytest.mark.parametrize(("status", "category"), [
    (400, "REQUEST_OR_MODEL"), (401, "AUTH"), (402, "BILLING"),
    (403, "AUTH"), (404, "REQUEST_OR_MODEL"), (429, "RATE_LIMIT"),
    (500, "UPSTREAM"), (503, "UPSTREAM"), (418, "HTTP_OTHER"),
])
def test_probe_http_status_is_safely_categorized(status, category):
    assert classify_status(status) == category


def test_probe_workflow_is_manual_confirmed_and_secret_safe():
    workflow = Path(".github/workflows/engineering-autonomy-deepseek-probe.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "inputs.confirm == true" in workflow
    assert "default: false" in workflow
    assert "timeout-minutes: 3" in workflow
    assert "timeout --signal=TERM --kill-after=5s 50s python -m engineering_autonomy.deepseek_probe" in workflow
    assert "persist-credentials: false" in workflow
    assert "secrets.DEEPSEEK_API_KEY" in workflow
    assert "schedule:" not in workflow
    assert "gh pr merge" not in workflow
    assert "curl -v" not in workflow
    assert "aider" not in workflow.lower().split("run: |")[-1]


def test_coding_pilot_cap_preflight_precedes_aider_install():
    """No extra paid probe; fail before installing Aider without an upstream cap."""
    path = Path(".github/workflows/engineering-autonomy-coding-v1-1.yml")
    coding = path.read_text(encoding="utf-8")
    gate = "Require authenticated provider-side CNY 5 cap proof"
    install = "Install pinned Aider coding CLI"
    agent = "Run isolated DeepSeek coding agent"
    assert coding.index("Create trusted prompt and require DeepSeek secret") < coding.index(gate)
    assert coding.index(gate) < coding.index(install) < coding.index(agent)
    assert "python -m engineering_autonomy.deepseek_budget cost-cap-check" in coding
    assert "python -m engineering_autonomy.deepseek_probe" not in coding
    assert "secrets.DEEPSEEK_API_KEY" in coding
    assert "GITHUB_TOKEN: ''" in coding
    assert "GH_TOKEN: ''" in coding
    assert "workflow_dispatch:" in coding
    assert "inputs.confirm == true" in coding
    assert "schedule:" not in coding
    assert "python -m engineering_autonomy.coding_gate capture --output /tmp/autonomy.patch" in coding
