"""Owner-only GitHub comment trigger for preexisting read-only AWS audit.

Deterministic, offline test contract. Does not contact AWS, GitHub or SSM.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.authorize_cloud_ops_comment import authorized, main

OWNER = "sample-owner"
COMMAND = "/stock-razor cloud-audit"


def event(**overrides):
    item = {
        "action": "created",
        "issue": {"number": 71, "pull_request": {"url": "https://example.invalid/pr"}},
        "comment": {
            "user": {"login": OWNER},
            "author_association": "OWNER",
            "body": COMMAND,
            "api_key": "SECRET_DO_NOT_RETURN",
        },
    }
    item.update(overrides)
    return item


def test_only_owner_exact_created_comment_on_control_pr_is_accepted():
    assert authorized("issue_comment", OWNER, OWNER, event()) is True
    assert authorized("issue_comment", "outsider", OWNER, event()) is False
    assert authorized("workflow_run", OWNER, OWNER, event()) is False


@pytest.mark.parametrize("changes", [
    {"action": "edited"},
    {"issue": {"number": 72, "pull_request": {}}},
    {"issue": {"number": True, "pull_request": {}}},
    {"issue": {"number": 71}},
    {"issue": {"number": 71, "pull_request": "present"}},
    {"comment": {"user": {"login": OWNER}, "author_association": "OWNER",
                 "body": COMMAND + "; echo secret"}},
    {"comment": {"user": {"login": OWNER}, "author_association": "MEMBER",
                 "body": COMMAND}},
    {"comment": {"user": {"login": "not-owner"}, "author_association": "OWNER",
                 "body": COMMAND}},
    {"comment": {"user": {"login": OWNER}, "author_association": "OWNER",
                 "body": COMMAND + " "}},
    {"comment": None},
    {"issue": None},
])
def test_negative_comment_variants_fail_closed(changes):
    assert authorized("issue_comment", OWNER, OWNER, event(**changes)) is False


def test_invalid_payload_does_not_bypass_checks():
    for payload in (None, {}, [], "some text", {"action": "created"}):
        assert authorized("issue_comment", OWNER, OWNER, payload) is False
    assert authorized("issue_comment", OWNER, "", event()) is False


def test_workflow_dispatch_keeps_prior_manual_mode():
    assert authorized("workflow_dispatch", OWNER, OWNER, {}) is True


def test_cli_never_prints_untrusted_message_or_secret(monkeypatch, tmp_path, capsys):
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event()), encoding="utf-8")
    for key, value in {
        "GITHUB_EVENT_NAME": "issue_comment", "GITHUB_ACTOR": OWNER,
        "GITHUB_REPOSITORY_OWNER": OWNER, "GITHUB_EVENT_PATH": str(path),
    }.items():
        monkeypatch.setenv(key, value)
    assert main() == 0
    assert capsys.readouterr().out.strip() == "CLOUD_OPS_COMMENT_ADMISSION=PASS"

    path.write_text(json.dumps(event(action="edited")), encoding="utf-8")
    assert main() == 2
    assert capsys.readouterr().out.strip() == "CLOUD_OPS_COMMENT_ADMISSION=BLOCKED"

    path.write_text("invalid-json SECRET_DO_NOT_RETURN", encoding="utf-8")
    assert main() == 2
    output = capsys.readouterr().out
    assert "SECRET_DO_NOT_RETURN" not in output
    assert "BLOCKED" in output

    path.write_text("Z" * (128 * 1024 + 1), encoding="utf-8")
    assert main() == 2
    assert "BLOCKED" in capsys.readouterr().out


def test_workflow_keeps_strict_pre_oidc_and_pre_ssm_guards():
    source = Path(".github/workflows/audit-cloud-independent-runtime.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in source and "issue_comment:" in source
    assert "types: [created]" in source
    assert "github.actor == github.repository_owner" in source
    assert "github.event.comment.author_association == 'OWNER'" in source
    assert "github.event.issue.number == 71" in source
    assert "github.event.comment.body == '/stock-razor cloud-audit'" in source
    assert "script_sha=" in source
    assert "persist-credentials: false" in source
    assert source.index("authorize_cloud_ops_comment.py") < source.index(
        "Configure temporary GitHub OIDC credentials"
    )
    assert source.index("AUDIT_MAIN_MOVED_ABORT") < source.index(
        "Configure temporary GitHub OIDC credentials"
    )
    assert source.index("AUDIT_PRE_SSM_MAIN_MOVED_ABORT") < source.index(
        "aws ssm send-command"
    )
    assert "systemctl restart" not in source
    assert "systemctl stop" not in source
