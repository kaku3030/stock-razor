#!/usr/bin/env python3
"""Fail-closed admission for one owner-only read-only AWS audit comment.

GitHub issue_comment payloads are untrusted input. This module authorizes
only a fixed command from the authenticated repository owner on one known
merged PR. It returns no comment text or credentials, and performs no AWS I/O.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_ANCHOR_PULL_REQUEST = 665
_ALLOWED_COMMAND = "/stock-razor aws-audit read-only"
_TICKFLOW_ANCHOR_PULL_REQUEST = 658
_TICKFLOW_ALLOWED_COMMAND = "/stock-razor tickflow-audit read-only"
_MAX_EVENT_BYTES = 262_144


def authorized_owner_comment(
    event: object, *, actor: str, repository: str, event_name: str,
) -> bool:
    if event_name != "issue_comment" or not isinstance(event, dict):
        return False
    if not isinstance(repository, str) or repository.count("/") != 1:
        return False
    owner, name = repository.split("/")
    if not owner or not name or actor != owner:
        return False
    if event.get("action") != "created":
        return False
    repo = event.get("repository")
    sender = event.get("sender")
    issue = event.get("issue")
    comment = event.get("comment")
    if not all(isinstance(item, dict) for item in (repo, sender, issue, comment)):
        return False
    if repo.get("full_name") != repository:
        return False
    comment_user = comment.get("user")
    if (sender.get("login") != owner or not isinstance(comment_user, dict)
            or comment_user.get("login") != owner):
        return False
    pr_number = issue.get("number")
    if type(pr_number) is not int or pr_number not in (
        _ANCHOR_PULL_REQUEST, _TICKFLOW_ANCHOR_PULL_REQUEST,
    ):
        return False
    if not isinstance(issue.get("pull_request"), dict):
        return False
    if type(comment.get("id")) is not int or comment["id"] <= 0:
        return False
    if comment.get("author_association") != "OWNER":
        return False
    expected_command = (
        _ALLOWED_COMMAND if pr_number == _ANCHOR_PULL_REQUEST
        else _TICKFLOW_ALLOWED_COMMAND
    )
    return type(comment.get("body")) is str and comment["body"] == expected_command


def main() -> int:
    allowed = False
    try:
        path = Path(os.environ["GITHUB_EVENT_PATH"])
        if not path.is_file() or not 0 < path.stat().st_size <= _MAX_EVENT_BYTES:
            raise ValueError("invalid event size")
        event: Any = json.loads(path.read_text(encoding="utf-8"))
        allowed = authorized_owner_comment(
            event, actor=os.environ["GITHUB_ACTOR"],
            repository=os.environ["GITHUB_REPOSITORY"],
            event_name=os.environ["GITHUB_EVENT_NAME"],
        )
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        allowed = False
    # No user-controlled event bytes, AWS errors or secrets in stdout/stderr.
    print("AWS_READONLY_OWNER_COMMENT=" + ("AUTHORIZED" if allowed else "BLOCKED"))
    return 0 if allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
