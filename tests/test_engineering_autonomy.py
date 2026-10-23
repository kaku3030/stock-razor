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


def test_previous_run_id_fails_closed_on_corrupt_record(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    (root / "100.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        previous_run_id(root)


@pytest.mark.parametrize(
    "payload",
    [
        ["100"],
        None,
        {"status": "PASS"},
        {"run_id": 100},
        {"run_id": "abc"},
    ],
)
def test_previous_run_id_rejects_malformed_record(tmp_path, payload):
    root = tmp_path / "runs"
    root.mkdir()
    (root / "100.json").write_text(json.dumps({"run_id": "100"}), encoding="utf-8")
    (root / "101.json").write_text(json.dumps(payload), encoding="utf-8")
    assert previous_run_id(root) is None
