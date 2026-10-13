#!/usr/bin/env python3
"""Fail-closed GitHub event admission for existing bounded Cloud Ops read-only audit.

Never grants credentials. This gate runs before the existing AWS OIDC step.
No comments, secrets, or arbitrary shell commands are ever evaluated.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


_CONTROL_PR = 71
_COMMAND = "/stock-razor cloud-audit"
_MAX_EVENT_BYTES = 128 * 1024


def authorized(event_name: str, actor: str, owner: str, payload: object) -> bool:
    if event_name == "workflow_dispatch":
        # Existing manually authorized workflow_dispatch behavior is unchanged.
        return True
    if event_name != "issue_comment" or not actor or actor != owner:
        return False
    if not isinstance(payload, dict) or payload.get("action") != "created":
        return False
    issue, comment = payload.get("issue"), payload.get("comment")
    if not isinstance(issue, dict) or not isinstance(comment, dict):
        return False
    # Fixed, known control PR (not any issue) in this single repository.
    if type(issue.get("number")) is not int or issue["number"] != _CONTROL_PR:
        return False
    if not isinstance(issue.get("pull_request"), dict):
        return False
    user = comment.get("user")
    return bool(
        isinstance(user, dict)
        and user.get("login") == owner
        and comment.get("author_association") == "OWNER"
        and comment.get("body") == _COMMAND
    )


def main() -> int:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    actor = os.environ.get("GITHUB_ACTOR", "")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    # A bogus event / malformed JSON must never grant AWS credentials.
    if event_name == "workflow_dispatch":
        accepted = bool(actor and owner)
    else:
        accepted = False
        try:
            path = Path(os.environ["GITHUB_EVENT_PATH"])
            if path.is_file() and 0 < path.stat().st_size <= _MAX_EVENT_BYTES:
                payload = json.loads(path.read_text(encoding="utf-8"))
                accepted = authorized(event_name, actor, owner, payload)
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            pass
    print("CLOUD_OPS_COMMENT_ADMISSION=" + ("PASS" if accepted else "BLOCKED"))
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
