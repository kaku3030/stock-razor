import json

import pytest

from engineering_autonomy.feedback_hub import FeedbackHub
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
    # Offline fixtures explicitly provision their persistent store before
    # invoking run_queue; production must never create it implicitly.
    feedback = FeedbackHub(tmp_path / "feedback.sqlite3")
    feedback.close()
    return path


def test_queue_rejects_unknown_fields(tmp_path):
    path = queue_file(tmp_path)
    data = json.loads(path.read_text())
    data["tasks"][0]["unsafe"] = True
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_queue(path)


def test_retry_and_checkpoint_then_resume(tmp_path):
    queue = queue_file(tmp_path)
    state = tmp_path / "state.json"
    feedback = tmp_path / "feedback.sqlite3"
    calls = []
    codes = iter([1, 0])
    result = run_queue(queue, state, feedback_path=feedback,
                       executor=lambda task: (calls.append(task.id), next(codes))[1])
    assert result["status"] == "PASS"
    assert calls == ["one", "one"]
    persisted = json.loads(state.read_text())
    assert persisted["attempts"]["one"] == 2
    resumed = run_queue(queue, state, feedback_path=feedback, executor=lambda task: 99)
    assert resumed["status"] == "PASS"
    assert resumed["completed"] == ["one"]


def test_cost_budget_blocks_before_execution(tmp_path):
    queue = queue_file(tmp_path, cost_units=2)
    state = tmp_path / "state.json"
    feedback = tmp_path / "feedback.sqlite3"
    called = []
    result = run_queue(queue, state, budget_units=1, feedback_path=feedback,
                       executor=lambda task: called.append(task.id) or 0)
    assert result["status"] == "BLOCKED"
    assert called == []


def test_stop_switch_stops_before_work(tmp_path, monkeypatch):
    queue = queue_file(tmp_path)
    state = tmp_path / "state.json"
    feedback = tmp_path / "feedback.sqlite3"
    monkeypatch.setenv("AUTONOMY_STOP", "true")
    result = run_queue(queue, state, feedback_path=feedback, executor=lambda task: 0)
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
    feedback = tmp_path / "feedback.sqlite3"
    assert run_queue(queue, state, feedback_path=feedback, executor=lambda task: 0)["status"] == "PASS"
    data = json.loads(queue.read_text())
    data["tasks"][0]["cost_units"] = 2
    queue.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="fingerprint"):
        load_state(state, load_queue(queue))


def test_each_retry_consumes_budget(tmp_path):
    queue = queue_file(tmp_path, cost_units=2)
    state = tmp_path / "state.json"
    feedback = tmp_path / "feedback.sqlite3"
    calls = []
    result = run_queue(
        queue, state, budget_units=3, feedback_path=feedback,
        executor=lambda task: calls.append(task.id) or 1,
    )
    assert result["status"] == "BLOCKED"
    assert result["spent_cost_units"] == 2
    assert result["attempts"]["one"] == 1
    assert calls == ["one"]


def test_default_executor_deadline_is_enforced(tmp_path, monkeypatch):
    import subprocess
    from engineering_autonomy import loop
    queue = queue_file(tmp_path)
    state = tmp_path / "state.json"
    feedback = tmp_path / "feedback.sqlite3"
    called = []

    def timeout_run(command, *, check, timeout):
        called.append(timeout)
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(loop.subprocess, "run", timeout_run)
    result = run_queue(queue, state, max_runtime_seconds=4, feedback_path=feedback)
    assert result["status"] == "STOPPED"
    assert result["spent_cost_units"] == 1
    assert called and 0 < called[0] <= 4


def test_invalid_attempt_checkpoint_fails_closed(tmp_path):
    queue = queue_file(tmp_path)
    state = tmp_path / "state.json"
    feedback = tmp_path / "feedback.sqlite3"
    run_queue(queue, state, feedback_path=feedback, executor=lambda task: 0)
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
