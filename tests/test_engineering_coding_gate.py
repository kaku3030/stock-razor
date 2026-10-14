import json
from pathlib import Path

import pytest

from engineering_autonomy.coding_gate import (
    ALLOWED_PATH,
    TASK_ID,
    validate_patch,
    validate_task,
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
