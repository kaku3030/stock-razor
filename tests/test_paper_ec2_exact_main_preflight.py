"""Exact production Paper EC2 source preflight under a fake Git executable.

Never assume AWS credentials, issue SSM commands or place broker orders.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/probe-paper-ec2-isolated-noorder.yml"
SHA = "a" * 40
OTHER_SHA = "b" * 40


def _source_preflight():
    data = WORKFLOW.read_text(encoding="utf-8")
    start = data.index("      - name: Verify scope, git identity and payload before assuming AWS role")
    end = data.index("      - name: Assume existing GitHub Ops", start)
    block = data[start:end]
    assert block.count("        run: |") == 1
    return "\n".join(
        line[10:] if line.startswith("          ") else ""
        for line in block.split("        run: |\n", 1)[1].splitlines()
    )


def _check(tmp_path, **changes):
    git = tmp_path / "git"
    git.write_text(
        '#!/bin/sh\n'
        'case "$1" in\n'
        '  rev-parse) printf "%s\\n" "$FAKE_HEAD";;\n'
        '  ls-remote) printf "%s\\trefs/heads/main\\n" "$FAKE_MAIN";;\n'
        '  *) exit 99;;\n'
        'esac\n',
        encoding="utf-8",
    )
    git.chmod(0o755)
    env = os.environ.copy()
    env.update({
        "PATH": str(tmp_path) + os.pathsep + env["PATH"],
        "FAKE_HEAD": SHA,
        "FAKE_MAIN": SHA,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": SHA,
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "EXPECTED_RUNTIME_SHA": OTHER_SHA,
        "RADAR_ADMISSION": "BLOCKED",
        "SOURCE_ARBITER_ADMISSION": "BLOCKED",
        "PAPER_AUTO_READY": "NO",
        "LIVE_TRADE": "NO",
        "TRADE_EXECUTION": "NO",
    })
    env.update(changes)
    return subprocess.run(
        ["bash", "-c", _source_preflight()], cwd=ROOT,
        env=env, capture_output=True, text=True, timeout=5, check=False,
    )


def test_paper_ec2_exact_current_main_and_fail_closed_before_oidc():
    s = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in s
    assert "  push:" not in s
    assert "  schedule:" not in s
    assert "github.ref == 'refs/heads/main' && inputs.approve_ephemeral_noorder_probe == true" in s
    assert "persist-credentials: false" in s
    assert s.index("Verify scope, git identity and payload before assuming AWS role") < s.index(
        "aws-actions/configure-aws-credentials@v4"
    )
    script = _source_preflight()
    assert 'test "$GITHUB_REF" = refs/heads/main' in script
    assert 'test "$revision" = "$GITHUB_SHA"' in script
    assert "git ls-remote origin refs/heads/main" in script
    assert "PAPER_EC2_MAIN_MOVED_ABORT" in script
    assert 'test "${TRADE_EXECUTION}" = NO' in script
    assert "systemctl" not in s


def test_paper_ec2_valid_current_main_preflight_is_only_local_source_verification(tmp_path):
    p = _check(tmp_path)
    assert p.returncode == 0, p.stderr
    assert "payload_sha256=" in (tmp_path / "output").read_text()
    assert not p.stdout


@pytest.mark.parametrize("change", [
    {"GITHUB_REF": "refs/heads/untrusted"},
    {"GITHUB_SHA": OTHER_SHA},
    {"FAKE_HEAD": OTHER_SHA},
    {"FAKE_MAIN": OTHER_SHA},
    {"FAKE_MAIN": ""},
    {"EXPECTED_RUNTIME_SHA": "invalid"},
    {"RADAR_ADMISSION": "OPEN"},
    {"SOURCE_ARBITER_ADMISSION": "OPEN"},
    {"PAPER_AUTO_READY": "YES"},
    {"LIVE_TRADE": "YES"},
    {"TRADE_EXECUTION": "YES"},
])
def test_paper_ec2_incorrect_branch_sha_or_safety_vetoes_without_aws(tmp_path, change):
    p = _check(tmp_path, **change)
    assert p.returncode != 0
    if (tmp_path / "output").exists():
        assert "payload_sha256=" not in (tmp_path / "output").read_text()
    assert "secret" not in p.stdout.lower()


def test_paper_ec2_main_race_is_explicitly_rejected(tmp_path):
    p = _check(tmp_path, FAKE_MAIN=OTHER_SHA)
    assert p.returncode == 2
    assert "PAPER_EC2_MAIN_MOVED_ABORT" in p.stderr
