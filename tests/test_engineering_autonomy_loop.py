import json

import pytest

from engineering_autonomy.loop import ALLOWED_COMMANDS, load_queue, load_state, run_queue


def queue_file(tmp_path, cost_units=1):
    path = tmp_path / "queue.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "tasks": [{
            "id": "one",
            "kind": "quality-check",
            "command": list(ALLOWED_COMMANDS["quality-check"]),
            "max_attempts": 2,
            "cost_units": cost_units,
        }]
    }), encoding="utf-8")
    return path


def test_queue_rejects_unknown_fields(tmp_path):
    path = queue_file(tmp_path)
    data = json.loads(path.read_text())
    data["tasks"][0]["unsafe"] = True
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_queue(path)


def test_no_identical_retry_and_durable_unknown_receipt(tmp_path):
    queue = queue_file(tmp_path)
    state = tmp_path / "state.json"
    calls = []
    codes = iter([1, 0])
    result = run_queue(queue, state, executor=lambda task: (calls.append(task.id), next(codes))[1])
    assert result["status"] == "BLOCKED"
    assert calls == ["one"]
    persisted = json.loads(state.read_text())
    assert persisted["attempts"]["one"] == 1
    assert persisted["failed"] == ["one"]
    incident = json.loads((tmp_path / "incidents.json").read_text())
    assert incident["records"][0]["exit_code"] == 1
    assert incident["records"][0]["diagnosis"] == "UNKNOWN_PENDING_ROOT_CAUSE"
    assert incident["records"][0]["source_sha"] == __import__("os").environ.get("GITHUB_SHA", "UNKNOWN").lower()
    resumed = run_queue(queue, state, executor=lambda task: 99)
    assert resumed["status"] == "BLOCKED"
    assert calls == ["one"]


def test_cost_budget_blocks_before_execution(tmp_path):
    queue = queue_file(tmp_path, cost_units=2)
    state = tmp_path / "state.json"
    called = []
    result = run_queue(queue, state, budget_units=1, executor=lambda task: called.append(task.id) or 0)
    assert result["status"] == "BLOCKED"
    assert called == []


def test_stop_switch_stops_before_work(tmp_path, monkeypatch):
    queue = queue_file(tmp_path)
    state = tmp_path / "state.json"
    monkeypatch.setenv("AUTONOMY_STOP", "true")
    result = run_queue(queue, state, executor=lambda task: 0)
    assert result["status"] == "STOPPED"
    assert result["completed"] == []


def test_queue_rejects_unsupported_kind(tmp_path):
    path = queue_file(tmp_path)
    data = json.loads(path.read_text())
    data["tasks"][0]["kind"] = "deploy"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_queue(path)


def test_queue_rejects_unreviewed_command(tmp_path):
    queue = queue_file(tmp_path)
    data = json.loads(queue.read_text())
    data["tasks"][0]["command"] = ["python", "-c", "print(123)"]
    queue.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="reviewed read-only"):
        load_queue(queue)


def test_changed_queue_cannot_resume_checkpoint(tmp_path):
    queue = queue_file(tmp_path)
    state = tmp_path / "state.json"
    assert run_queue(queue, state, executor=lambda task: 0)["status"] == "PASS"
    data = json.loads(queue.read_text())
    data["tasks"][0]["cost_units"] = 2
    queue.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="fingerprint"):
        load_state(state, load_queue(queue))


def test_each_retry_consumes_budget(tmp_path):
    queue = queue_file(tmp_path, cost_units=2)
    state = tmp_path / "state.json"
    calls = []
    result = run_queue(queue, state, budget_units=3,
        executor=lambda task: calls.append(task.id) or 1)
    assert result["status"] == "BLOCKED"
    assert result["spent_cost_units"] == 2
    assert result["attempts"]["one"] == 1
    assert calls == ["one"]


def test_default_executor_deadline_is_enforced(tmp_path, monkeypatch):
    import subprocess
    from engineering_autonomy import loop
    queue = queue_file(tmp_path)
    state = tmp_path / "state.json"
    called = []

    def timeout_run(command, *, check, timeout):
        called.append(timeout)
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(loop.subprocess, "run", timeout_run)
    result = run_queue(queue, state, max_runtime_seconds=4)
    assert result["status"] == "BLOCKED"
    assert result["spent_cost_units"] == 1
    incident = json.loads((tmp_path / "incidents.json").read_text())
    assert incident["records"][0]["exit_code"] == -124
    assert called and 0 < called[0] <= 4


def test_invalid_attempt_checkpoint_fails_closed(tmp_path):
    queue = queue_file(tmp_path)
    state = tmp_path / "state.json"
    run_queue(queue, state, executor=lambda task: 0)
    saved = json.loads(state.read_text())
    saved["attempts"]["one"] = -1
    state.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="attempt count"):
        load_state(state, load_queue(queue))


def test_resume_requires_exact_cache_hit():
    from pathlib import Path

    workflow = Path(".github/workflows/engineering-autonomy-120m.yml").read_text(
        encoding="utf-8"
    )
    assert "id: resume-cache" in workflow
    assert "steps.resume-cache.outputs.cache-hit != 'true'" in workflow
    assert "fail-on-cache-miss: true" in workflow
    assert "restore-keys:" not in workflow
