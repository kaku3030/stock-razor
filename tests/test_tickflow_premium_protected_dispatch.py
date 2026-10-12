"""TickFlow paid AWS probe must reject bad ref, SHA and spend scope before OIDC.

Execute exactly the checked-in preflight in a synthetic environment with a fake
git executable. No AWS, TickFlow network, credentials or live market requests.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


WORKFLOW = Path(".github/workflows/probe-tickflow-aws-premium.yml")
PRE_NAME = "Preflight exact protected main and premium scope before AWS OIDC"
OIDC_NAME = "- uses: aws-actions/configure-aws-credentials@v4"
SHA = "a" * 40
OTHER_SHA = "b" * 40


def _preflight_source() -> str:
    source = WORKFLOW.read_text(encoding="utf-8")
    pre = source.index("      - name: " + PRE_NAME)
    oidc = source.index("      " + OIDC_NAME)
    assert pre < oidc
    tail = source[pre:oidc]
    assert tail.count("        run: |") == 1
    return "\n".join(
        line[10:] if line.startswith("          ") else ""
        for line in tail.split("        run: |\n", 1)[1].splitlines()
    )


def _run_preflight(tmp_path, **overrides):
    fake_git = tmp_path / "git"
    fake_git.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  rev-parse) printf '%s\\n' \"$FAKE_GIT_HEAD\";;\n"
        "  ls-remote) printf '%s\\trefs/heads/main\\n' \"$FAKE_GIT_MAIN\";;\n"
        "  *) exit 99;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    env = os.environ.copy()
    env.update({
        "PATH": str(tmp_path) + os.pathsep + env["PATH"],
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": SHA,
        "FAKE_GIT_HEAD": SHA,
        "FAKE_GIT_MAIN": SHA,
        "SECRET_ARN": "",
        "QUOTE_ONLY": "true",
        "WS_SECONDS": "0",
    })
    env.update(overrides)
    return subprocess.run(
        ["bash", "-c", _preflight_source()],
        capture_output=True, text=True, timeout=5, env=env, check=False,
    )


def test_paid_probe_requires_explicit_manual_main_job_gate_and_pre_oidc_validation():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "  push:" not in source
    assert "  schedule:" not in source
    assert "github.ref == 'refs/heads/main' && inputs.enable_premium_probe == true" in source
    script = _preflight_source()
    assert "git ls-remote origin refs/heads/main" in script
    assert '"$revision" == "$GITHUB_SHA"' in script
    assert "TICKFLOW_PREMIUM_MAIN_MOVED_ABORT" in script
    assert '"$QUOTE_ONLY" == true && "$WS_SECONDS" != 0' in script
    assert "test -s scripts/probe_tickflow_isolated.py" in script
    assert "configure-aws-credentials@v4" in source


def test_valid_protected_main_quote_only_runs_preflight_without_aws(tmp_path):
    result = _run_preflight(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not result.stdout


@pytest.mark.parametrize("overrides", [
    {"GITHUB_REF": "refs/heads/untrusted-feature"},
    {"GITHUB_SHA": OTHER_SHA},
    {"FAKE_GIT_HEAD": OTHER_SHA},
    {"FAKE_GIT_MAIN": OTHER_SHA},
    {"FAKE_GIT_MAIN": ""},
    {"WS_SECONDS": "100"},
    {"WS_SECONDS": "-1"},
    {"WS_SECONDS": "10", "QUOTE_ONLY": "true"},
    {"QUOTE_ONLY": "yes"},
    {"SECRET_ARN": "other-secret"},
    {"SECRET_ARN": "arn:aws:secretsmanager:us-east-1:888425712426:secret:stock-razor/tickflow/premium-api-key-ABCDEF"},
])
def test_bad_branch_sha_cost_scope_or_secret_stops_before_oidc(tmp_path, overrides):
    result = _run_preflight(tmp_path, **overrides)
    assert result.returncode != 0
    assert "secret:" not in result.stdout
    assert "secret:" not in result.stderr


def test_explicit_standard_ws_scope_still_allowed_but_never_grants_live_gate(tmp_path):
    result = _run_preflight(
        tmp_path, WS_SECONDS="30", QUOTE_ONLY="false",
        SECRET_ARN="stock-razor/tickflow/premium-api-key",
    )
    assert result.returncode == 0, result.stderr
    source = WORKFLOW.read_text(encoding="utf-8")
    assert 'data.get("data_qualification") == "NOT_VERIFIED"' in source
    assert 'data.get("radar_admission") == "BLOCKED"' in source
    assert 'record["provider_live_qualified"]=False' in source
