import json
from pathlib import Path

import pytest

from engineering_autonomy.coding_gate import (
    ALLOWED_PATH,
    TASK_ID,
    validate_patch,
    validate_task,
    verify_worktree,
)


def make_patch(path=ALLOWED_PATH):
    return (f"diff --git a/{path} b/{path}\n"
            "index 1234567..abcdef0 100644\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            "@@ -1 +1,2 @@\n a\n+b\n").encode()


def test_allowlisted_patch_is_accepted():
    validate_patch(make_patch())


def test_autonomy_workflow_protects_gitignore_from_agent_writes():
    workflow = Path(".github/workflows/engineering-autonomy-coding-v1-1.yml").read_text(
        encoding="utf-8"
    )
    assert "--file tests/test_engineering_autonomy.py \\\n            --read .gitignore \\\n            --no-gitignore" in workflow



def test_manual_coding_pilot_requires_explicit_one_shot_confirmation():
    workflow = Path(".github/workflows/engineering-autonomy-coding-v1-1.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in workflow
    assert "type: boolean" in workflow
    assert "default: false" in workflow
    assert "inputs.confirm == true" in workflow
    assert "ENGINEERING_CODING_ENABLED" not in workflow
    assert "schedule:" not in workflow



@pytest.mark.parametrize("patch", [
    b"", b"bad", make_patch("src/trading.py"),
    make_patch() + b"\x00",
    make_patch() + b"diff --git a/tests/test_engineering_autonomy.py b/tests/test_engineering_autonomy.py\n",
    make_patch().replace(b"index 1234567..abcdef0 100644", b"new file mode 100644"),
    make_patch() + b"A" * 16384,
])
def test_malformed_patch_is_rejected(patch):
    with pytest.raises(ValueError):
        validate_patch(patch)


def test_unknown_manifest_field_is_rejected(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"version": 1, "tasks": [
        {"id": TASK_ID, "enabled": True, "command": "run-anything"}]}))
    with pytest.raises(ValueError):
        validate_task(path)


def test_disabled_task_is_rejected(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"version": 1, "tasks": [{"id": TASK_ID, "enabled": False}]}))
    with pytest.raises(ValueError):
        validate_task(path)


def test_workflow_uses_deepseek_aider_without_codex_or_openai_secret():
    workflow = Path('.github/workflows/engineering-autonomy-coding-v1-1.yml').read_text(
        encoding='utf-8'
    )
    assert 'secrets.DEEPSEEK_API_KEY' in workflow
    assert 'aider-chat==0.86.2' in workflow
    assert '--file tests/test_engineering_autonomy.py' in workflow
    assert '--model deepseek/deepseek-chat' in workflow
    assert 'openai/codex-action' not in workflow
    assert 'secrets.OPENAI_API_KEY' not in workflow


def test_aider_history_files_outside_checkout_and_capture_still_fail_closed():
    workflow = Path(".github/workflows/engineering-autonomy-coding-v1-1.yml").read_text(
        encoding="utf-8"
    )
    assert '--input-history-file "$RUNNER_TEMP/autonomy-aider-input.history"' in workflow
    assert '--chat-history-file "$RUNNER_TEMP/autonomy-aider-chat.history.md"' in workflow
    assert "--map-tokens 0" in workflow
    assert "--no-gitignore" in workflow
    assert "--no-analytics" in workflow
    assert 'git", "status", "--porcelain=v1", "-z", "--untracked-files=all"' in workflow
    assert "python -m engineering_autonomy.coding_gate capture --output /tmp/autonomy.patch" in workflow
    assert "git clean" not in workflow
    assert "git restore" not in workflow


def test_porcelain_unstaged_edit_preserves_significant_leading_space(monkeypatch):
    """Aider's one allowed unstaged edit must pass strict capture."""
    expected_status = f" M {ALLOWED_PATH}".encode() + bytes([0])
    observed_commands = []

    def fake_git(command, **kwargs):
        observed_commands.append(command)
        if command[:2] == ["git", "status"]:
            return expected_status
        if command[:2] == ["git", "diff"]:
            return make_patch()
        raise AssertionError(f"Unexpected subprocess: {command}")

    monkeypatch.setattr("engineering_autonomy.coding_gate.subprocess.check_output", fake_git)
    assert verify_worktree() == make_patch()
    assert observed_commands[0] == [
        "git", "status", "--porcelain=v1", "-z", "--untracked-files=all"
    ]


@pytest.mark.parametrize("status", [
    b"",
    b" M tests/test_engineering_autonomy.py\n",
    b"M  tests/test_engineering_autonomy.py\0",
    b"MM tests/test_engineering_autonomy.py\0",
    b"?? .aider-chat.history.md\0",
    b" M tests/test_engineering_autonomy.py\0?? .aider-chat.history.md\0",
])
def test_porcelain_unreviewed_changes_still_fail_closed(monkeypatch, status):
    """Staged, extra, missing and malformed entries cannot pass capture."""
    def fake_git(command, **kwargs):
        if command[:2] == ["git", "status"]:
            return status
        raise AssertionError("Unexpected diff execution after a rejected status")

    monkeypatch.setattr("engineering_autonomy.coding_gate.subprocess.check_output", fake_git)
    with pytest.raises(ValueError, match="not one allowed modified test file"):
        verify_worktree()


def test_deepseek_provider_response_is_bounded():
    workflow = Path(".github/workflows/engineering-autonomy-coding-v1-1.yml").read_text(
        encoding="utf-8"
    )
    # Bounded whole-process duration, even when Aider/LiteLLM keep retrying.
    assert "timeout --signal=TERM --kill-after=10s 240s aider" in workflow
    assert "--timeout 90" in workflow
    assert "--no-stream" in workflow
    assert "--no-cache-prompts" in workflow
    assert "timeout-minutes: 8" in workflow
    assert 'if [ "$rc" -eq 124 ]; then' in workflow
    assert "DeepSeek/Aider exceeded 240-second overall limit" in workflow
    # The fail-closed capture and no-write-token generation job are unchanged.
    assert "python -m engineering_autonomy.coding_gate capture --output /tmp/autonomy.patch" in workflow
    assert "GITHUB_TOKEN: ''" in workflow
    assert "GH_TOKEN: ''" in workflow
    assert "--no-auto-commits" in workflow
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
