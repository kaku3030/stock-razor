"""Offline private migration blocker tests, without AWS or account activity."""
import json
from pathlib import Path
import subprocess
import sys

from scripts.audit_private_repo_cloud_readiness import (
    INSTALLER,
    KNOWN_BLOCKERS,
    VISIBILITY_ABORT_MARKER,
    WORKFLOW,
    review_private_repo_migration,
)


def _fixture(tmp_path, *, workflow, installer):
    for relative, text in ((WORKFLOW, workflow), (INSTALLER, installer)):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _guard():
    return (
        'if [[ "${{ github.event.repository.private }}" == "true" ]]; then\n'
        f'echo "{VISIBILITY_ABORT_MARKER}" >&2\n'
        "exit 3\nfi\n"
    )


def test_real_deployment_still_requires_public_source_delivery_and_blocks_flip():
    result = review_private_repo_migration(Path("."))
    assert result.status == "BLOCKED"
    assert result.reason == "KNOWN_UNAUTHENTICATED_CLOUD_SOURCE_DEPENDENCIES"
    assert result.deployment_private_guard_present
    assert len(result.known_blockers) == len(KNOWN_BLOCKERS)
    assert result.audited_workflow_count == 1
    assert result.scope == "US_OPEND_DEPLOY_PATH_ONLY"
    assert result.network_requests == result.aws_mutations == 0
    assert result.repo_visibility_mutations == 0
    assert result.radar_admission == result.source_arbiter_admission == "BLOCKED"
    assert not result.paper_auto_ready and not result.live_trade


def test_private_visibility_guard_fails_before_oidc_or_ssm_mutation():
    workflow = Path(WORKFLOW).read_text(encoding="utf-8")
    guard = workflow.index(VISIBILITY_ABORT_MARKER)
    aws_auth = workflow.index("aws-actions/configure-aws-credentials@")
    send_command = workflow.index("aws ssm send-command")
    assert guard < aws_auth < send_command
    assert 'github.event.repository.private' in workflow
    assert 'exit 3' in workflow
    assert 'approve_restart == true' in workflow
    assert 'inputs.expected_main_sha == github.sha' in workflow
    assert "raw.githubusercontent.com/kaku3030/stock-razor/" in workflow


def test_missing_guard_is_blocked_even_when_transport_appears_unchanged(tmp_path):
    fixture = _fixture(
        tmp_path,
        workflow="git ls-remote origin refs/heads/main",
        installer="git clone --filter=blob:none",
    )
    result = review_private_repo_migration(fixture)
    assert result.status == "BLOCKED"
    assert result.reason == "PRIVATE_REPOSITORY_FAIL_CLOSED_GUARD_MISSING"
    assert not result.deployment_private_guard_present


def test_no_known_pattern_is_unknown_not_safe_to_change_visibility(tmp_path):
    fixture = _fixture(
        tmp_path,
        workflow=_guard() + "echo local-bundle\n",
        installer="echo an-immutable-bundle\n",
    )
    result = review_private_repo_migration(fixture)
    assert result.status == "UNKNOWN"
    assert result.reason == "NO_KNOWN_BLOCKERS_BUT_PRIVATE_E2E_NOT_VERIFIED"
    assert result.known_blockers == ()
    assert result.deployment_private_guard_present


def test_missing_file_is_unknown_no_false_positive(tmp_path):
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / WORKFLOW).write_text(_guard())
    result = review_private_repo_migration(tmp_path)
    assert result.status == "UNKNOWN"
    assert result.reason == "REQUIRED_SOURCE_UNAVAILABLE"
    assert INSTALLER in result.missing_files
    assert result.network_requests == result.aws_mutations == 0


def test_private_audit_cli_returns_sanitized_machine_readable_block():
    r = subprocess.run(
        [sys.executable, "scripts/audit_private_repo_cloud_readiness.py"],
        text=True, capture_output=True, timeout=5, check=False,
    )
    assert r.returncode == 0
    item = json.loads(r.stdout)
    assert item["status"] == "BLOCKED"
    assert len(item["known_blockers"]) == 5
    assert item["repo_visibility_mutations"] == 0
    assert "ghp_" not in r.stdout
    assert "SECRET" not in r.stdout
