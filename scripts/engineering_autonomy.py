"""Fail-closed helpers for the Engineering Autonomy V1 workflow."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


TASK_MANIFEST = Path("docs/engineering-autonomy-tasks.json")
RECORD_ROOT = "docs/engineering-autonomy/runs"
TASK_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RUN_ID = re.compile(r"^[0-9]+$")
ALLOWED_TASK_KEYS = frozenset({"id", "kind", "path", "enabled"})
ALLOWED_KINDS = frozenset({"audit-only"})
ALLOWED_RECORD_KEYS = (
    "schema_version",
    "run_id",
    "base_sha",
    "task_id",
    "previous_run_id",
    "status",
    "reason",
)


def _text(value: Any, field: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    if pattern and not pattern.fullmatch(value):
        raise ValueError(f"{field} has an invalid format")
    return value


def load_tasks(path: Path = TASK_MANIFEST) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("task manifest version is unsupported")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("task manifest must contain tasks")
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict) or set(task) != ALLOWED_TASK_KEYS:
            raise ValueError("task contains unknown or missing fields")
        task_id = _text(task["id"], "task id", TASK_ID)
        if task_id in seen:
            raise ValueError("task ids must be unique")
        seen.add(task_id)
        if task["kind"] not in ALLOWED_KINDS:
            raise ValueError("task kind is not allowlisted")
        if task["path"] != RECORD_ROOT:
            raise ValueError("task path is not allowlisted")
        if not isinstance(task["enabled"], bool):
            raise ValueError("task enabled must be boolean")
        validated.append(task)
    return validated


def select_task(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    for task in tasks:
        if task["enabled"]:
            return task
    raise ValueError("no enabled task is available")


def previous_run_id(record_root: Path) -> str | None:
    records = sorted(record_root.glob("*.json")) if record_root.exists() else []
    if not records:
        return None
    payload = json.loads(records[-1].read_text(encoding="utf-8"))
    value = payload.get("run_id") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and RUN_ID.fullmatch(value) else None


def build_record(
    run_id: str,
    base_sha: str,
    task_id: str,
    prior_run_id: str | None,
    status: str,
    reason: str,
) -> dict[str, str | None]:
    _text(run_id, "run_id", RUN_ID)
    _text(base_sha, "base_sha", re.compile(r"^[0-9a-f]{40}$"))
    _text(task_id, "task_id", TASK_ID)
    if prior_run_id is not None:
        _text(prior_run_id, "previous_run_id", RUN_ID)
    if status not in {"PASS", "BLOCKED"}:
        raise ValueError("status is not allowlisted")
    _text(reason, "reason")
    return {
        "schema_version": "engineering-autonomy-v1",
        "run_id": run_id,
        "base_sha": base_sha,
        "task_id": task_id,
        "previous_run_id": prior_run_id,
        "status": status,
        "reason": reason,
    }


def write_record(record: dict[str, str | None], record_root: Path) -> Path:
    if tuple(record) != ALLOWED_RECORD_KEYS:
        raise ValueError("record schema is not allowlisted")
    record_root.mkdir(parents=True, exist_ok=True)
    destination = record_root / f"{record['run_id']}.json"
    if destination.exists():
        raise FileExistsError(destination)
    destination.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-manifest")
    record_parser = subparsers.add_parser("record-run")
    record_parser.add_argument("--run-id", required=True)
    record_parser.add_argument("--base-sha", required=True)
    record_parser.add_argument("--record-root", type=Path, default=Path(RECORD_ROOT))
    args = parser.parse_args()

    if args.command == "validate-manifest":
        task = select_task(load_tasks())
        print(task["id"])
        return 0

    task = select_task(load_tasks())
    prior = previous_run_id(args.record_root)
    destination = write_record(
        build_record(
            args.run_id,
            args.base_sha,
            task["id"],
            prior,
            "PASS",
            "bounded audit-only task completed",
        ),
        args.record_root,
    )
    print(destination.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
