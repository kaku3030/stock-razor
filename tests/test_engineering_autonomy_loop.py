import json

import pytest

from engineering_autonomy.loop import load_queue, run_queue


def queue_file(tmp_path):
    path = tmp_path / "queue.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "tasks": [{
            "id": "one",
            "kind": "quality-check",
            "command": ["python", "-c", "pass"],
            "max_attempts": 2,
            "cost_units": 1,
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


def test_retry_and_checkpoint_then_resume(tmp_path):
    queue = queue_file(tmp_path)
    state = tmp_path / "state.json"
    calls = []
    codes = iter([1, 0])
    result = run_queue(queue, state, executor=lambda task: (calls.append(task.id), next(codes))[1])
    assert result["status"] == "PASS"
    assert calls == ["one", "one"]
    persisted = json.loads(state.read_text())
    assert persisted["attempts"]["one"] == 2
    resumed = run_queue(queue, state, executor=lambda task: 99)
    assert resumed["status"] == "PASS"
    assert resumed["completed"] == ["one"]


def test_cost_budget_blocks_before_execution(tmp_path):
    queue = queue_file(tmp_path)
    state = tmp_path / "state.json"
    called = []
    result = run_queue(queue, state, budget_units=1, executor=lambda task: called.append(task.id) or 0)
    assert result["status"] == "PASS"
    assert called == ["one"]


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
