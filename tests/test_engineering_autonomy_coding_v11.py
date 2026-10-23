"""No credentials or GitHub access required for V1.1 safety-gate tests."""
import json
import pytest
from engineering_autonomy.coding_v11 import choose_task, validate_paths

GOOD = {
    "version": 1,
    "tasks": [{"id": "expand-autonomy-tests", "kind": "test-only", "enabled": True,
               "paths": ["tests/test_engineering_autonomy.py"]}],
}


def test_select_exact_allowlisted_task(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(GOOD))
    assert choose_task(p) == "expand-autonomy-tests"


def test_disabled_task_does_not_execute(tmp_path):
    p = tmp_path / "manifest.json"
    data = json.loads(json.dumps(GOOD))
    data["tasks"][0]["enabled"] = False
    p.write_text(json.dumps(data))
    assert choose_task(p) is None


@pytest.mark.parametrize("extra", [
    {"shell": "echo unsafe"},
    {"paths": ["src/services/context_manager.py"]},
    {"kind": "deploy"},
    {"enabled": 1},
    {"id": "unsafe-task"},
])
def test_manifest_rejects_unreviewed_task_attributes(tmp_path, extra):
    data = json.loads(json.dumps(GOOD))
    data["tasks"][0].update(extra)
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        choose_task(p)


@pytest.mark.parametrize("paths", [
    [],
    ["tests/test_engineering_autonomy.py", "src/services/context_manager.py"],
    ["tests/test_engineering_autonomy.py", "tests/test_engineering_autonomy.py"],
    ["tests/../tests/test_engineering_autonomy.py"],
    [".github/workflows/engineering-autonomy-v1.yml"],
])
def test_patch_paths_fail_closed(paths):
    with pytest.raises(ValueError):
        validate_paths(paths)


def test_exact_single_test_file_allowed():
    validate_paths(["tests/test_engineering_autonomy.py"])


def test_staged_gate_accepts_only_target_test_and_rejects_other_path(tmp_path, monkeypatch):
    import subprocess
    from engineering_autonomy.coding_v11 import check_staged

    monkeypatch.chdir(tmp_path)

    def git(*args):
        subprocess.run(["git", *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    (tmp_path / "tests").mkdir()
    target = tmp_path / "tests" / "test_engineering_autonomy.py"
    target.write_text("def test_one():\n    assert True\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    forbidden = tmp_path / "src" / "production.py"
    forbidden.write_text("safe = True\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "initial")
    target.write_text("def test_one():\n    assert 1 == 1\n", encoding="utf-8")
    git("add", "tests/test_engineering_autonomy.py")
    check_staged()
    forbidden.write_text("safe = False\n", encoding="utf-8")
    git("add", "src/production.py")
    with pytest.raises(ValueError, match="only one approved test file"):
        check_staged()
