"""De-duplicated GitHub Issue reminders for DeepSeek API funds.

No DeepSeek key is available here. Consume only sanitized categorical balance
data and use GH_TOKEN with issues:write; never print or publish account amounts.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from engineering_autonomy.deepseek_budget import ISSUE_TITLE, read_status

ALERT_STATES = {"LOW", "EMPTY", "UNAVAILABLE"}


def gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=25, check=False,
    )
    if result.returncode:
        raise RuntimeError("GitHub Issues request failed")
    return result.stdout.strip()


def reconcile_status(status: str, repo: str, owner: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("invalid repository")
    if not re.fullmatch(r"[A-Za-z0-9-]+", owner):
        raise ValueError("invalid owner")
    if status not in ALERT_STATES | {"OK", "UNKNOWN"}:
        raise ValueError("invalid status")
    if status == "UNKNOWN":
        return "UNKNOWN_NO_BALANCE_CLAIM"

    # Iterate ALL open issues to avoid a substring-search false positive. Exit
    # on malformed/failed listing, rather than creating a possible duplicate.
    issues = json.loads(
        gh("issue", "list", "--repo", repo, "--state", "open", "--limit", "5000",
           "--json", "number,title,body")
    )
    if not isinstance(issues, list):
        raise ValueError("malformed issues list")
    matches = [i for i in issues if isinstance(i, dict) and i.get("title") == ISSUE_TITLE]
    if len(matches) > 1:
        raise ValueError("duplicate alerts require manual cleanup")
    current = matches[0] if matches else None
    if status == "OK":
        if current:
            gh("issue", "close", str(current["number"]), "--repo", repo,
               "--comment", "DeepSeek official balance check is healthy again; closing this alert.")
            return "RECOVERED_CLOSED"
        return "OK_NO_ALERT"
    notice = (
        "STOCK RAZOR Engineering Autonomy: DeepSeek API balance alert.\n\n"
        f"DEEPSEEK_BUDGET_STATUS={status}\n\n"
        "LOW: below early-warning threshold (CNY 10 / USD 2); paid coding is blocked.\n"
        "EMPTY: no available funds; top up the DeepSeek API account.\n"
        "UNAVAILABLE: DeepSeek says balance is unusable; check billing, key and account.\n\n"
        "This monitor sends no generation requests, does not recharge automatically, "
        "and never reveals the API key or exact balance. "
        "Recharge/check account at the official DeepSeek developer console. "
        "Once balance is healthy the next monitor run will close this issue."
    )
    if not current:
        gh("issue", "create", "--repo", repo, "--title", ISSUE_TITLE,
           "--body", notice, "--assignee", owner)
        return "ALERT_CREATED"
    body = current.get("body")
    if not isinstance(body, str):
        raise ValueError("invalid alert issue")
    if f"DEEPSEEK_BUDGET_STATUS={status}\n" not in body:
        gh("issue", "edit", str(current["number"]), "--repo", repo, "--body", notice)
        gh("issue", "comment", str(current["number"]), "--repo", repo,
           "--body", "DeepSeek balance alert severity changed to " + status
           + ". Please check the DeepSeek developer console.")
        return "ALERT_UPDATED"
    return "ALERT_ALREADY_OPEN"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", type=Path, required=True)
    args = parser.parse_args()
    # Neither raw balance, DeepSeek keys nor third-party API credentials
    # are visible to this notification process.
    if not os.environ.get("GH_TOKEN"):
        print("BUDGET_ALERT=NO_GITHUB_CREDENTIAL")
        return 2
    try:
        status = read_status(args.status_file)
        result = reconcile_status(
            status, os.environ.get("GITHUB_REPOSITORY", ""),
            os.environ.get("GITHUB_REPOSITORY_OWNER", ""),
        )
    except (ValueError, TypeError, KeyError, OSError, RuntimeError,
            json.JSONDecodeError, subprocess.TimeoutExpired):
        print("BUDGET_ALERT=FAILED_CLOSED")
        return 2
    print("BUDGET_ALERT=" + result)
    return 0 if status != "UNKNOWN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
