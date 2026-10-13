"""Owner-only GitHub comment -> existing AWS *read-only* runtime audit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.authorize_cloud_ops_audit_comment import (
    _ALLOWED_COMMAND,
    authorized_owner_comment,
    main,
)

OWNER = "kaku3030"
REPO = "kaku3030/stock-razor"


def make_event() -> dict:
    return {
        "action": "created",
        "repository": {"full_name": REPO},
        "sender": {"login": OWNER},
        "issue": {"number": 665, "pull_request": {"url": "fixed-pr"}},
        "comment": {
            "id": 123456, "body": _ALLOWED_COMMAND,
            "author_association": "OWNER", "user": {"login": OWNER},
        },
    }


def allowed(e: object, *, actor: str = OWNER, repository: str = REPO,
            event_name: str = "issue_comment") -> bool:
    return authorized_owner_comment(e, actor=actor, repository=repository,
                                    event_name=event_name)


def test_exact_owner_comment_accepts_one_fixed_readonly_command():
    assert allowed(make_event()) is True


@pytest.mark.parametrize("field,value", [
    ("action", "edited"),
    ("action", "deleted"),
    ("repository", {"full_name": "other/repo"}),
    ("sender", {"login": "attacker"}),
    ("issue", {"number": 71, "pull_request": {"url": "other"}}),
    ("issue", {"number": True, "pull_request": {"url": "bad"}}),
    ("issue", {"number": 665}),
    ("comment", {"id": 123, "body": _ALLOWED_COMMAND, "user": {"login": OWNER}}),
    ("comment", {"id": 123, "body": _ALLOWED_COMMAND + " ", "author_association": "OWNER", "user": {"login": OWNER}}),
    ("comment", {"id": 123, "body": _ALLOWED_COMMAND + "\nrun arbitrary command", "author_association": "OWNER", "user": {"login": OWNER}}),
    ("comment", {"id": 123, "body": "/stock-razor aws-restart", "author_association": "OWNER", "user": {"login": OWNER}}),
    ("comment", {"id": True, "body": _ALLOWED_COMMAND, "author_association": "OWNER", "user": {"login": OWNER}}),
    ("comment", {"id": 123, "body": _ALLOWED_COMMAND, "author_association": "OWNER", "user": None}),
])
def test_mutated_or_malformed_events_block(field, value):
    event = make_event()
    event[field] = value
    assert allowed(event) is False


@pytest.mark.parametrize("kwargs", [
    {"actor": "someone-else"},
    {"actor": ""},
    {"repository": "not-a-repository"},
    {"repository": "evil/repository"},
    {"event_name": "pull_request"},
    {"event_name": "workflow_dispatch"},
])
def test_untrusted_github_execution_contexts_block(kwargs):
    assert allowed(make_event(), **kwargs) is False


def test_non_mapping_payload_or_missing_keys_block():
    for event in (None, [], "event", {}, {"comment": None},
                  {"issue": {"number": 665}}, 13):
        assert allowed(event) is False


def test_main_prints_only_enum_and_never_event_payload(monkeypatch, tmp_path, capsys):
    path = tmp_path / "github-event.json"
    event = make_event()
    event["untrusted_secret"] = "TEST_SECRET_NEVER_ECHO"
    path.write_text(json.dumps(event), encoding="utf-8")
    for key, val in {
        "GITHUB_EVENT_PATH": str(path),
        "GITHUB_ACTOR": OWNER,
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_EVENT_NAME": "issue_comment",
    }.items():
        monkeypatch.setenv(key, val)
    assert main() == 0
    assert capsys.readouterr().out == "AWS_READONLY_OWNER_COMMENT=AUTHORIZED\n"
    event["comment"]["body"] = _ALLOWED_COMMAND + " && TEST_SECRET_NEVER_ECHO"
    path.write_text(json.dumps(event), encoding="utf-8")
    assert main() == 2
    captured = capsys.readouterr()
    assert captured.out == "AWS_READONLY_OWNER_COMMENT=BLOCKED\n"
    assert "TEST_SECRET_NEVER_ECHO" not in (captured.out + captured.err)
    path.write_bytes(b"x" * 270000)
    assert main() == 2
    assert capsys.readouterr().out == "AWS_READONLY_OWNER_COMMENT=BLOCKED\n"


def test_workflow_double_guards_before_iam_and_keeps_manual_dispatch():
    workflow = Path(".github/workflows/audit-cloud-independent-runtime.yml").read_text(
        encoding="utf-8"
    )
    assert "  workflow_dispatch:" in workflow
    assert "  issue_comment:\n    types: [created]" in workflow
    assert "github.event.issue.number == 665" in workflow
    assert "github.event.comment.body == '/stock-razor aws-audit read-only'" in workflow
    assert "github.actor == github.repository_owner" in workflow
    assert "github.event.comment.user.login == github.repository_owner" in workflow
    assert "github.event.comment.author_association == 'OWNER'" in workflow
    assert "github.event.issue.pull_request != null" in workflow
    assert "github.event_name == 'workflow_dispatch' ||" in workflow
    assert workflow.index("Validate owner-only comment") < workflow.index(
        "Configure temporary GitHub OIDC credentials"
    )
    assert workflow.index("AUDIT_MAIN_MOVED_ABORT") < workflow.index(
        "Configure temporary GitHub OIDC credentials"
    )
    assert workflow.index("AUDIT_PRE_SSM_MAIN_MOVED_ABORT") < workflow.index(
        "aws ssm send-command"
    )
    assert "python3 scripts/authorize_cloud_ops_audit_comment.py" in workflow
    assert "github.event.comment.body }}\n" not in workflow
    assert "aws ssm send-command" in workflow
    assert "RADAR_ADMISSION=BLOCKED" in workflow
    assert "LIVE_TRADE=NO" in workflow
