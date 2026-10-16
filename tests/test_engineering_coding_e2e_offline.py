"""Hermetic end-to-end proof of test-only patch capture and publication gates.

Runs against disposable local Git repositories without tokens, Aider, network
requests, real PR creation, production code or trading endpoints.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from engineering_autonomy.coding_gate import ALLOWED_PATH, validate_patch

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, cwd: Path, ok: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        args, cwd=cwd, env=env, text=True, capture_output=True, timeout=30, check=False
    )
    if ok and proc.returncode:
        raise AssertionError(f"Safe local command failed: {args[0:3]}, code={proc.returncode}")
    return proc


def git(cwd: Path, *args: str) -> str:
    return run("git", *args, cwd=cwd).stdout.strip()


def seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "disposable-source"
    (repo / "docs").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs/engineering-autonomy-coding-tasks.json").write_text(
        (ROOT / "docs/engineering-autonomy-coding-tasks.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo / ALLOWED_PATH).write_text(
        "def test_baseline():\n    assert True\n", encoding="utf-8"
    )
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "offline-test-only")
    git(repo, "config", "user.email", "offline-test-only@example.invalid")
    git(repo, "add", "--", "docs/engineering-autonomy-coding-tasks.json", ALLOWED_PATH)
    git(repo, "commit", "-qm", "offline baseline")
    return repo


def cli(cwd: Path, action: str, output: Path, *, ok: bool = True):
    return run(
        sys.executable, "-m", "engineering_autonomy.coding_gate", action,
        "--output", str(output), cwd=cwd, ok=ok,
    )


def test_offline_capture_verify_and_publication_staging(tmp_path):
    """Run actual CLI and git apply commands across three fresh workspaces."""
    source = seed_repo(tmp_path)
    (source / ALLOWED_PATH).write_text(
        "def test_baseline():\n    assert True\n\n"
        "def test_new_regression():\n    assert 2 + 2 == 4\n", encoding="utf-8",
    )
    patch = tmp_path / "agent-untrusted.patch"
    assert "PASS: capture" in cli(source, "capture", patch).stdout
    validate_patch(patch.read_bytes())

    verifier = tmp_path / "fresh-secretless-verifier"
    run("git", "clone", "-q", "--no-local", str(source), str(verifier), cwd=tmp_path)
    assert "PASS: check-patch" in cli(verifier, "check-patch", patch).stdout
    git(verifier, "apply", "--check", str(patch))
    git(verifier, "apply", str(patch))
    reverified = tmp_path / "verified.patch"
    assert "PASS: capture" in cli(verifier, "capture", reverified).stdout
    assert reverified.read_bytes() == patch.read_bytes()
    assert "2 passed" in run(
        sys.executable, "-m", "pytest", "-q", ALLOWED_PATH,
        cwd=verifier,
    ).stdout

    publisher = tmp_path / "fresh-publication-staging"
    run("git", "clone", "-q", "--no-local", str(source), str(publisher), cwd=tmp_path)
    assert "PASS: check-patch" in cli(publisher, "check-patch", reverified).stdout
    git(publisher, "apply", "--check", str(reverified))
    git(publisher, "apply", "--index", str(reverified))
    git(publisher, "diff", "--cached", "--check")
    assert git(publisher, "diff", "--cached", "--name-only") == ALLOWED_PATH
    assert git(publisher, "status", "--porcelain=v1") == f"M  {ALLOWED_PATH}"
    # No PR, git push or remote mutation is performed by this test.


@pytest.mark.parametrize("extra_path", [".aider-chat.history.md", "src/trading.py"])
def test_offline_capture_rejects_all_extra_workspace_changes(tmp_path, extra_path):
    source = seed_repo(tmp_path)
    (source / ALLOWED_PATH).write_text("def test_baseline():\n    assert False\n")
    artifact = source / extra_path
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("untrusted change\n", encoding="utf-8")
    patch = tmp_path / "must-not-exist.patch"
    result = cli(source, "capture", patch, ok=False)
    assert result.returncode != 0
    assert "not one allowed modified test file" in result.stderr
    assert not patch.exists()


def test_offline_verification_rejects_tampered_second_file(tmp_path):
    source = seed_repo(tmp_path)
    (source / ALLOWED_PATH).write_text("def test_baseline():\n    assert False\n")
    patch = tmp_path / "legitimate.patch"
    cli(source, "capture", patch)
    bad_patch = tmp_path / "unreviewed-second-file.patch"
    bad_patch.write_bytes(
        patch.read_bytes()
        + b"diff --git a/src/risk.py b/src/risk.py\n"
        + b"new file mode 100644\n--- /dev/null\n+++ b/src/risk.py\n"
        + b"@@ -0,0 +1 @@\n+UNSAFE=True\n"
    )
    assert cli(source, "check-patch", bad_patch, ok=False).returncode != 0
    with pytest.raises(ValueError, match="Patch paths not allowlisted"):
        validate_patch(bad_patch.read_bytes())
