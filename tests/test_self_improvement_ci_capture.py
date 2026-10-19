"""Automated CI error capture stays redacted and does not infer bug resolution."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.self_improvement_ci_capture import (
    CaptureError, build_receipt, SCHEMA,
)

SHA = "a" * 40
OBSERVED = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def receipt(jobs):
    return build_receipt(
        workflow="CI", run_id="394442211", head_sha=SHA,
        jobs=jobs, observed=OBSERVED,
    )


def test_one_failed_job_captured_as_unknown_and_shareable():
    v = receipt([{"name": "backend-gate", "conclusion": "failure"}])
    assert v["schema"] == SCHEMA
    assert v["incidents"][0]["root_cause"] == "UNKNOWN_PENDING_ROOT_CAUSE"
    assert v["incidents"][0]["action"] == "DIAGNOSE_ONCE_AND_ADD_REGRESSION"
    assert v["cross_window_lookup"] == "GITHUB_ACTIONS_RUN_ARTIFACT"
    assert v["run_url"].endswith("/394442211")
    assert v["head_sha"] == SHA


def test_same_failure_across_revisions_has_stable_family():
    jobs = [{"name": "focused-tests", "conclusion": "timed_out"}]
    first = receipt(jobs)["incidents"][0]["failure_family"]
    second = build_receipt(workflow="CI", run_id="394442212",
                           head_sha="b" * 40, jobs=jobs)["incidents"][0]["failure_family"]
    assert first == second


def test_different_component_is_different_family():
    one = receipt([{"name": "backend-gate", "conclusion": "failure"}])
    two = receipt([{"name": "focused-tests", "conclusion": "failure"}])
    assert one["incidents"][0]["failure_family"] != two["incidents"][0]["failure_family"]


def test_duplicate_jobs_dedupe_and_success_is_ignored():
    v = receipt([
        {"name": "backend-tests (1/3)", "conclusion": "failure"},
        {"name": "backend-tests (1/3)", "conclusion": "failure"},
        {"name": "backend-tests (2/3)", "conclusion": "success"},
    ])
    assert len(v["incidents"]) == 1


def test_empty_job_failure_keeps_unknown_not_success():
    v = receipt([{"name": "backend-gate", "conclusion": "success"}])
    assert v["incidents"][0]["job"] == "UNKNOWN_JOB_NAME"
    assert v["incidents"][0]["root_cause"] == "UNKNOWN_PENDING_ROOT_CAUSE"


@pytest.mark.parametrize("fields", [
    {"run_id": "not_number"},
    {"head_sha": "main"},
    {"workflow": "arbitrary external workflow"},
    {"jobs": [{"name": "a", "conclusion": "failure", "raw_log": "key"}]},
])
def test_untrusted_fields_refused(fields):
    kwargs = {"workflow": "CI", "run_id": "333", "head_sha": SHA,
              "jobs": [{"name": "backend-gate", "conclusion": "failure"}]}
    kwargs.update(fields)
    with pytest.raises(CaptureError):
        build_receipt(**kwargs)


def test_unsafe_job_name_is_not_exported():
    v = receipt([{"name": "secret=ABCD;curl https://example.com", "conclusion": "failure"}])
    assert v["incidents"][0]["job"] == "UNKNOWN_JOB_NAME"
    assert "ABCD" not in json.dumps(v)


def test_workflow_metadata_only_no_logs_no_write_permission():
    workflow = Path(".github/workflows/self-improvement-ci-failure-capture.yml").read_text(
        encoding="utf-8")
    assert "workflow_run:" in workflow
    assert "workflows: [CI, \"Research Radar Tests\"]" in workflow
    assert "actions: read" in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "download" not in workflow.lower()
    assert "jq -s '{jobs:[.[].jobs[] | {name,conclusion}]}'" in workflow
    assert "actions/upload-artifact@v4" in workflow


def test_cli_stores_only_sanitized_artifact(tmp_path):
    data = {"jobs": [{"name": "backend-gate", "conclusion": "failure"}]}
    src = tmp_path / "jobs.json"
    dest = tmp_path / "out.json"
    src.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run([
        sys.executable, "scripts/self_improvement_ci_capture.py",
        "--input", str(src), "--output", str(dest),
        "--workflow", "CI", "--run-id", "331", "--head-sha", SHA,
    ], check=False, capture_output=True, text=True)
    assert result.returncode == 0
    out = json.loads(dest.read_text())
    assert out["incidents"][0]["job"] == "backend-gate"
    assert "CI_UNKNOWN_INCIDENT_RECEIPT=RECORDED" in result.stdout
