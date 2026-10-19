"""Bounded, resumable Engineering Autonomy queue runner.

This module is intentionally provider-agnostic. It executes only reviewed task
kinds, checkpoints state atomically, retries within a finite budget, and stops
when a local stop file or AUTONOMY_STOP=true is observed. It does not merge,
deploy, schedule, or trade.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from engineering_autonomy.incident_memory import observe_failure

SCHEMA_VERSION = 1
ALLOWED_COMMANDS = {
    "quality-check": (
        "python", "-m", "pytest", "-q",
        "tests/test_engineering_autonomy.py", "tests/test_engineering_coding_gate.py",
    ),
    "e2e-evidence": (
        "python", "-m", "pytest", "-q", "tests/test_engineering_coding_gate.py",
    ),
}
ALLOWED_KINDS = frozenset(ALLOWED_COMMANDS)
MAX_TASKS = 32
MAX_ATTEMPTS = 3
MAX_COST_UNITS = 32
MAX_RUNTIME_SECONDS = 120 * 60
DEFAULT_QUEUE = Path("engineering_autonomy/queue.json")
DEFAULT_STATE = Path("engineering_autonomy/state.json")
STOP_FILE = Path("engineering_autonomy/STOP")

@dataclass(frozen=True)
class Task:
    id: str
    kind: str
    command: tuple[str, ...]
    max_attempts: int
    cost_units: int

def _bounded_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ValueError(f"{field} must be a short non-empty string")
    return value

def load_queue(path: Path = DEFAULT_QUEUE) -> list[Task]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported queue schema")
    raw = payload.get("tasks")
    if not isinstance(raw, list) or not raw or len(raw) > MAX_TASKS:
        raise ValueError("queue size is outside bounds")
    result: list[Task] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or set(item) != {
            "id", "kind", "command", "max_attempts", "cost_units"
        }:
            raise ValueError("task fields are not allowlisted")
        task_id = _bounded_text(item["id"], "task id")
        if task_id in seen or any(c in task_id for c in "/\\"):
            raise ValueError("task ids must be unique and path-safe")
        seen.add(task_id)
        kind = item["kind"]
        if kind not in ALLOWED_KINDS:
            raise ValueError("task kind is not allowlisted")
        command = item["command"]
        if not isinstance(command, list) or not command or any(
            not isinstance(part, str) or not part or len(part) > 200 for part in command
        ):
            raise ValueError("task command is invalid")
        if tuple(command) != ALLOWED_COMMANDS[kind]:
            raise ValueError("task command is not a reviewed read-only check")
        attempts = item["max_attempts"]
        cost = item["cost_units"]
        if type(attempts) is not int or not 1 <= attempts <= MAX_ATTEMPTS:
            raise ValueError("max_attempts is outside bounds")
        if type(cost) is not int or not 1 <= cost <= MAX_COST_UNITS:
            raise ValueError("cost_units is outside bounds")
        result.append(Task(task_id, kind, tuple(command), attempts, cost))
    return result

def _queue_fingerprint(queue: list[Task]) -> str:
    canonical = [
        [task.id, task.kind, list(task.command), task.max_attempts, task.cost_units]
        for task in queue
    ]
    raw = json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


def _initial_state(queue: list[Task]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "queue_sha256": _queue_fingerprint(queue),
        "status": "RUNNING",
        "next_index": 0,
        "attempts": {task.id: 0 for task in queue},
        "completed": [],
        "failed": [],
        "spent_cost_units": 0,
        "updated_at_epoch": 0,
    }

def load_state(path: Path, queue: list[Task]) -> dict[str, Any]:
    if not path.exists():
        return _initial_state(queue)
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported state schema")
    if set(state) != {
        "schema_version", "queue_sha256", "status", "next_index", "attempts", "completed",
        "failed", "spent_cost_units", "updated_at_epoch"
    }:
        raise ValueError("state fields are not allowlisted")
    if state["queue_sha256"] != _queue_fingerprint(queue):
        raise ValueError("checkpoint queue fingerprint mismatch")
    if state["status"] not in {"RUNNING", "STOPPED", "PASS", "BLOCKED"}:
        raise ValueError("invalid state status")
    ids = [task.id for task in queue]
    if not isinstance(state["attempts"], dict) or set(state["attempts"]) != set(ids):
        raise ValueError("state does not match queue")
    if any(
        type(state["attempts"][task.id]) is not int
        or not 0 <= state["attempts"][task.id] <= task.max_attempts
        for task in queue
    ):
        raise ValueError("invalid checkpoint attempt count")
    if type(state["next_index"]) is not int or not 0 <= state["next_index"] <= len(ids):
        raise ValueError("invalid next_index")
    if type(state["spent_cost_units"]) is not int or state["spent_cost_units"] < 0:
        raise ValueError("invalid spent cost")
    if not isinstance(state["completed"], list) or not isinstance(state["failed"], list):
        raise ValueError("invalid result lists")
    if any(item not in ids for item in state["completed"] + state["failed"]):
        raise ValueError("state contains an unknown task result")
    if len(state["completed"]) != len(set(state["completed"])) or len(state["failed"]) != len(set(state["failed"])):
        raise ValueError("state contains duplicate task results")
    if set(state["completed"]) & set(state["failed"]):
        raise ValueError("task cannot be both completed and failed")
    if state["completed"] != ids[:state["next_index"]]:
        raise ValueError("checkpoint completed tasks do not match queue position")
    if state["failed"] and (
        len(state["failed"]) != 1
        or state["next_index"] >= len(ids)
        or state["failed"][0] != ids[state["next_index"]]
    ):
        raise ValueError("checkpoint failure does not match queue position")
    if state["status"] == "PASS" and state["next_index"] != len(ids):
        raise ValueError("incomplete queue cannot be marked PASS")
    return state

def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)

def stop_requested(stop_file: Path = STOP_FILE) -> bool:
    return os.environ.get("AUTONOMY_STOP", "").lower() == "true" or stop_file.exists()

def run_queue(
    queue_path: Path = DEFAULT_QUEUE,
    state_path: Path = DEFAULT_STATE,
    budget_units: int = MAX_COST_UNITS,
    max_runtime_seconds: int = MAX_RUNTIME_SECONDS,
    executor: Callable[[Task], int] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if type(budget_units) is not int or not 1 <= budget_units <= MAX_COST_UNITS:
        raise ValueError("budget_units is outside bounds")
    if type(max_runtime_seconds) is not int or not 1 <= max_runtime_seconds <= MAX_RUNTIME_SECONDS:
        raise ValueError("max_runtime_seconds is outside bounds")
    queue = load_queue(queue_path)
    state = load_state(state_path, queue)
    if state["status"] in {"PASS", "BLOCKED"}:
        return state
    started = clock()

    def checkpoint(status: str) -> dict[str, Any]:
        state["status"] = status
        state["updated_at_epoch"] = int(time.time())
        save_state(state_path, state)
        return state

    def bounded_executor(task: Task) -> int:
        remaining = max_runtime_seconds - (clock() - started)
        if remaining <= 0:
            raise subprocess.TimeoutExpired(task.command, timeout=0)
        return subprocess.run(task.command, check=False, timeout=remaining).returncode

    executor = executor or bounded_executor

    def retain_unknown_failure(task: Task, code: int) -> None:
        # Preserve the BLOCKED checkpoint first, then a durable sanitized
        # incident receipt. Raw command output and exception text never cross.
        state["failed"].append(task.id)
        checkpoint("BLOCKED")
        observe_failure(
            state_path.with_name("incidents.json"), task_id=task.id,
            kind=task.kind, exit_code=code, queue_sha=_queue_fingerprint(queue),
            source_sha=os.environ.get("GITHUB_SHA", "UNKNOWN").lower(),
            environment=("github-actions" if os.environ.get("GITHUB_ACTIONS") == "true"
                         else "local"),
            run_id=os.environ.get("GITHUB_RUN_ID", "UNKNOWN"),
        )

    checkpoint("RUNNING")
    while state["next_index"] < len(queue):
        task = queue[state["next_index"]]
        attempts = state["attempts"][task.id]
        success = False
        while attempts < task.max_attempts:
            if stop_requested() or clock() - started >= max_runtime_seconds:
                return checkpoint("STOPPED")
            # Each retry consumes an explicit cost unit; persist BEFORE the call.
            if state["spent_cost_units"] + task.cost_units > budget_units:
                return checkpoint("BLOCKED")
            attempts += 1
            state["attempts"][task.id] = attempts
            state["spent_cost_units"] += task.cost_units
            checkpoint("RUNNING")
            try:
                code = executor(task)
            except subprocess.TimeoutExpired:
                retain_unknown_failure(task, -124)
                return state
            except Exception:
                # No raw exception/traceback is exported to the shared ledger.
                retain_unknown_failure(task, -125)
                return state
            if code == 0:
                success = True
                break
            # A deterministic task with unchanged code/environment does NOT
            # get a free repeat of the same failed command. A revised task or
            # verified new condition must create a new explicit run/checkpoint.
            retain_unknown_failure(task, code)
            return state
        if success:
            state["completed"].append(task.id)
            state["next_index"] += 1
            checkpoint("RUNNING")
        else:
            return checkpoint("BLOCKED")
    return checkpoint("PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--budget-units", type=int, default=MAX_COST_UNITS)
    parser.add_argument("--max-runtime-seconds", type=int, default=MAX_RUNTIME_SECONDS)
    args = parser.parse_args()
    state = run_queue(args.queue, args.state, args.budget_units, args.max_runtime_seconds)
    print(json.dumps(state, sort_keys=True))
    return 0 if state["status"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
