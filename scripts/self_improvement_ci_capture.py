#!/usr/bin/env python3
"""Redacted automatic capture of previously unknown GitHub CI failures.

Reads only GitHub's bounded job name + conclusion metadata; NEVER logs,
exception messages, raw provider data or secrets. Emits portable evidence to
a GitHub Actions artifact so any connected Stock Razor window can inspect it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "stock-razor-ci-unknown-incident-v1"
SHA = re.compile(r"^[0-9a-f]{40}$")
WORKFLOWS = frozenset({"CI", "Research Radar Tests"})
FAILURES = frozenset({"failure", "timed_out", "action_required"})
RUNID = re.compile(r"^[0-9]{1,20}$")
JOB = re.compile(r"^[A-Za-z0-9_. ()/-]{1,120}$")
MAX_JOBS = 100


class CaptureError(ValueError):
    pass


def build_receipt(*, workflow, run_id, head_sha, jobs, observed=None):
    if workflow not in WORKFLOWS:
        raise CaptureError("UNKNOWN_WORKFLOW")
    if not isinstance(run_id, str) or not RUNID.fullmatch(run_id):
        raise CaptureError("INVALID_RUN_ID")
    if not isinstance(head_sha, str) or not SHA.fullmatch(head_sha):
        raise CaptureError("INVALID_HEAD_SHA")
    if not isinstance(jobs, list) or len(jobs) > MAX_JOBS:
        raise CaptureError("INVALID_JOB_LIST")
    stamp = observed or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        raise CaptureError("UNTRUSTED_TIMESTAMP")
    incidents = []
    seen = set()
    for raw in jobs:
        if not isinstance(raw, dict) or set(raw) != {"name", "conclusion"}:
            raise CaptureError("UNTRUSTED_JOB_FIELDS")
        conclusion = raw["conclusion"]
        if conclusion not in FAILURES:
            continue
        job = raw["name"]
        # Unknown job metadata is not echoed into artifacts, to prevent
        # raw log/error injection or accidental inclusion of secret values.
        job = job if isinstance(job, str) and JOB.fullmatch(job) else "UNKNOWN_JOB_NAME"
        family = hashlib.sha256(
            json.dumps([workflow, job, conclusion], separators=(",", ":")).encode("ascii")
        ).hexdigest()
        if family in seen:
            continue
        seen.add(family)
        incidents.append({
            "failure_family": family,
            "workflow": workflow, "job": job,
            "conclusion": conclusion,
            "root_cause": "UNKNOWN_PENDING_ROOT_CAUSE",
            "action": "DIAGNOSE_ONCE_AND_ADD_REGRESSION",
            "previous_impact": "UNVERIFIED",
        })
    if not incidents:
        incidents.append({
            "failure_family": hashlib.sha256(
                (workflow + ":UNKNOWN_FAILURE_JOB").encode("ascii")).hexdigest(),
            "workflow": workflow, "job": "UNKNOWN_JOB_NAME",
            "conclusion": "UNKNOWN",
            "root_cause": "UNKNOWN_PENDING_ROOT_CAUSE",
            "action": "INVESTIGATE_MISSING_OR_UNOBSERVED_JOB",
            "previous_impact": "UNVERIFIED",
        })
    return {
        "schema": SCHEMA,
        "repository": "kaku3030/stock-razor",
        "run_id": run_id,
        "run_url": "https://github.com/kaku3030/stock-razor/actions/runs/" + run_id,
        "head_sha": head_sha,
        "observed_at_utc": stamp.astimezone(timezone.utc).isoformat(),
        "incidents": incidents,
        "research_only": True,
        "new_bug_memory": "RECEIPT_ONLY_NOT_AUTOMATICALLY_RESOLVED",
        "cross_window_lookup": "GITHUB_ACTIONS_RUN_ARTIFACT",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args()
    if args.input.stat().st_size > 120_000:
        raise CaptureError("RAW_JOB_METADATA_OVERSIZED")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"jobs"}:
        raise CaptureError("INVALID_JOB_PROJECTION")
    result = build_receipt(workflow=args.workflow, run_id=args.run_id,
                           head_sha=args.head_sha, jobs=data["jobs"])
    encoded = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if len(encoded.encode()) > 20_000:
        raise CaptureError("REDACTED_RECEIPT_OVERSIZED")
    args.output.write_text(encoded, encoding="utf-8")
    print("CI_UNKNOWN_INCIDENT_RECEIPT=RECORDED")
    print("CI_UNKNOWN_INCIDENT_FAMILIES=" + str(len(result["incidents"])))


if __name__ == "__main__":
    main()
