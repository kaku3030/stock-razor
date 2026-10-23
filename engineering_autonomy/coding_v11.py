"""Fail-closed policy helpers for a test-only Engineering Autonomy coding pilot.

This policy is rechecked in a clean, secret-free GitHub Actions job after
model-generated changes are produced.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
from pathlib import Path

MANIFEST = Path("engineering_autonomy/coding_tasks.json")
TASK_IDS = frozenset({"expand-autonomy-tests"})
TEST_FILE = "tests/test_engineering_autonomy.py"
ALLOWED_PATHS = frozenset({TEST_FILE})
MAX_PATCH_BYTES = 60_000
MAX_CHANGED_LINES = 180


def choose_task(path: Path = MANIFEST) -> str | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"version", "tasks"} or data["version"] != 1:
        raise ValueError("invalid coding task schema")
    tasks = data["tasks"]
    if not isinstance(tasks, list) or len(tasks) != 1:
        raise ValueError("exactly one bounded coding task required")
    task = tasks[0]
    if not isinstance(task, dict) or set(task) != {"id", "kind", "enabled", "paths"}:
        raise ValueError("invalid coding task fields")
    if task["id"] not in TASK_IDS or task["kind"] != "test-only":
        raise ValueError("coding task not allowlisted")
    if type(task["enabled"]) is not bool or task["paths"] != [TEST_FILE]:
        raise ValueError("invalid task activation or path")
    return task["id"] if task["enabled"] else None


def validate_paths(paths: list[str]) -> None:
    if not paths or len(paths) != len(set(paths)) or set(paths) != ALLOWED_PATHS:
        raise ValueError("only one approved test file may change")
    for path in paths:
        if path.startswith("/") or ".." in Path(path).parts or "\\" in path:
            raise ValueError("unsafe path")


def _run_git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], stderr=subprocess.PIPE)


def check_staged(patch: Path | None = None) -> None:
    if patch is not None:
        if not patch.is_file() or patch.stat().st_size > MAX_PATCH_BYTES or patch.stat().st_size == 0:
            raise ValueError("patch size outside bounds")
    paths = _run_git("diff", "--cached", "--name-only", "-z").decode().rstrip("\0").split("\0")
    validate_paths(paths)
    if _run_git("diff", "--cached", "--summary").strip():
        raise ValueError("file mode, type or rename changes forbidden")
    stats = _run_git("diff", "--cached", "--numstat").decode().splitlines()
    if len(stats) != 1:
        raise ValueError("expected exactly one changed test")
    parts = stats[0].split("\t")
    if len(parts) != 3 or parts[2] != TEST_FILE or not re.fullmatch(r"\d+", parts[0]) or not re.fullmatch(r"\d+", parts[1]):
        raise ValueError("binary or malformed diff forbidden")
    if int(parts[0]) + int(parts[1]) > MAX_CHANGED_LINES:
        raise ValueError("change exceeds reviewed size ceiling")
    if len(_run_git("diff", "--cached", "--binary")) > MAX_PATCH_BYTES:
        raise ValueError("diff is too large")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["select-task", "check-staged"])
    parser.add_argument("--patch", type=Path)
    args = parser.parse_args()
    if args.command == "select-task":
        print(choose_task() or "NONE")
    else:
        check_staged(args.patch)
        print("ALLOWLIST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
