import json

import pytest

from scripts.engineering_autonomy import (
    build_record,
    load_tasks,
    previous_run_id,
    select_task,
    write_record,
)


def test_manifest_selects_only_allowlisted_task():
    task = select_task(load_tasks())
    assert task == {
        "id": "record-run",
        "kind": "audit-only",
        "path": "docs/engineering-autonomy/runs",
        "enabled": True,
    }


def test_unknown_task_fields_fail_closed(tmp_path):
    manifest = tmp_path / "tasks.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "tasks": [
                    {
                        "id": "record-run",
                        "kind": "audit-only",
                        "path": "docs/engineering-autonomy/runs",
                        "enabled": True,
                        "command": "echo unsafe",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_tasks(manifest)


def test_record_is_sanitized_and_chains_previous_run(tmp_path):
    root = tmp_path / "runs"
    first = build_record("100", "a" * 40, "record-run", None, "PASS", "ok")
    write_record(first, root)
    assert previous_run_id(root) == "100"
    second = build_record("101", "b" * 40, "record-run", "100", "PASS", "ok")
    destination = write_record(second, root)
    assert json.loads(destination.read_text(encoding="utf-8"))["previous_run_id"] == "100"


@pytest.mark.parametrize("status", ["UNKNOWN", "MERGED", ""])
def test_record_status_is_fail_closed(status):
    with pytest.raises(ValueError):
        build_record("100", "a" * 40, "record-run", None, status, "reason")


def test_autonomy_workflows_do_not_execute_self_merge():
    from pathlib import Path
    import re
    import yaml

    root = Path(__file__).resolve().parents[1]
    forbidden = re.compile(
        r"gh\s+pr\s+merge|enablePullRequestAutoMerge|pulls\.merge|/pulls/[^\s]+/merge"
    )
    for path in (root / ".github/workflows").glob("engineering-autonomy*.yml"):
        workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                assert not forbidden.search(step.get("run", "")), (
                    f"V5.1 forbids self-merge: {path.name}: {step.get('name')}"
                )
