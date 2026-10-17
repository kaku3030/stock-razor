from pathlib import Path


WORKFLOW = Path(".github/workflows/engineering-autonomy-v1.yml").read_text(
    encoding="utf-8"
)


def test_legacy_autonomy_workflow_is_manual_and_never_auto_merges():
    assert "workflow_dispatch:" in WORKFLOW
    assert "inputs:" in WORKFLOW
    assert "inputs.confirm == true" in WORKFLOW
    assert "default: false" in WORKFLOW
    assert "schedule:" not in WORKFLOW
    assert "gh pr merge" not in WORKFLOW
    assert "--auto" not in WORKFLOW


def test_legacy_autonomy_publisher_uses_short_lived_app_token_and_dedupes_branch():
    assert "actions/create-github-app-token@v2" in WORKFLOW
    assert "permission-contents: write" in WORKFLOW
    assert "permission-pull-requests: write" in WORKFLOW
    assert "steps.publish.outputs.token" in WORKFLOW
    assert "a PR already exists for this run branch" in WORKFLOW
    assert 'git push --set-upstream origin "autonomy/run-${RUN_ID}"' in WORKFLOW


def test_legacy_autonomy_workflow_checks_out_trigger_sha_without_persisting_credentials():
    checkout = WORKFLOW.split("- name: Checkout exact main", 1)[1].split(
        "- name: Setup Python", 1
    )[0]
    assert "ref: ${{ github.sha }}" in checkout
    assert "ref: main" not in checkout
    assert "persist-credentials: false" in checkout


def test_legacy_autonomy_audit_job_is_time_bounded():
    assert "timeout-minutes: 10" in WORKFLOW
    assert "concurrency:" in WORKFLOW
    assert "cancel-in-progress: false" in WORKFLOW


def test_legacy_autonomy_stages_only_one_run_json():
    assert 'RECORD="docs/engineering-autonomy/runs/${RUN_ID}.json"' in WORKFLOW
    assert 'test "$(git status --porcelain=v1 --untracked-files=all)" = "?? ${RECORD}"' in WORKFLOW
    assert 'git add -- "${RECORD}"' in WORKFLOW
    assert 'test "$(git diff --cached --name-only)" = "${RECORD}"' in WORKFLOW
    assert "git add docs/engineering-autonomy/runs" not in WORKFLOW
    assert "git diff --cached --check" in WORKFLOW
