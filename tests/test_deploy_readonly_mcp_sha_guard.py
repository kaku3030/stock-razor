"""No AWS access: test actual owner/main guard before a service-changing SSM deploy."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

FLOW = Path(".github/workflows/deploy-readonly-mcp.yml")


def _first_guard() -> str:
    data = FLOW.read_text(encoding="utf-8")
    chunk = data.split("      - name: Verify protected main before AWS identity\n", 1)[1]
    chunk = chunk.split("      - id: source\n", 1)[0]
    raw = chunk.split("        run: |\n", 1)[1]
    return "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in raw.splitlines()
    )


def test_mcp_owner_deploy_pre_iam_guard_actual_shell(tmp_path):
    """Trusted owner/main succeed; branch, stale source, API failure always veto."""
    fake = tmp_path / "bin"
    fake.mkdir()
    git = fake / "git"
    gh = fake / "gh"
    git.write_text(
        '#!/bin/sh\n'
        'test "$1" = rev-parse && test "$2" = HEAD || exit 5\n'
        'printf "%s\\n" "$MOCK_CHECKOUT_SHA"\n',
        encoding="utf-8",
    )
    gh.write_text(
        '#!/bin/sh\n'
        'test "$1" = api || exit 5\n'
        'test "$MOCK_GH_FAIL" != yes || exit 4\n'
        'printf "%s\\n" "$MOCK_MAIN_SHA"\n',
        encoding="utf-8",
    )
    git.chmod(0o755)
    gh.chmod(0o755)
    sha = "a" * 40
    env = dict(
        os.environ, PATH=str(fake) + os.pathsep + os.environ["PATH"],
        GITHUB_REF="refs/heads/main", GITHUB_ACTOR="kaku3030",
        GITHUB_REPOSITORY="kaku3030/stock-razor",
        GITHUB_SHA=sha, MOCK_CHECKOUT_SHA=sha, MOCK_MAIN_SHA=sha,
        MOCK_GH_FAIL="no", GH_TOKEN="SECRET_FIXTURE_NOT_LOGGABLE",
    )
    cases = [
        ({}, 0, ""),
        ({"GITHUB_ACTOR": "intruder"}, 2, "MCP_DEPLOY_UNAUTHORIZED_REF_OR_ACTOR"),
        ({"GITHUB_REF": "refs/heads/topic"}, 2, "MCP_DEPLOY_UNAUTHORIZED_REF_OR_ACTOR"),
        ({"MOCK_CHECKOUT_SHA": "b" * 40}, 2, "MCP_DEPLOY_CHECKOUT_SHA_MISMATCH"),
        ({"GITHUB_SHA": "not-a-sha"}, 2, "MCP_DEPLOY_CHECKOUT_SHA_MISMATCH"),
        ({"MOCK_MAIN_SHA": "b" * 40}, 2, "MCP_DEPLOY_MAIN_MOVED_ABORT"),
        ({"MOCK_GH_FAIL": "yes"}, 2, "MCP_DEPLOY_MAIN_LOOKUP_BLOCKED"),
    ]
    script = _first_guard()
    assert subprocess.run(["bash", "-n", "-c", script], check=False).returncode == 0
    for changes, expected_rc, marker in cases:
        result = subprocess.run(
            ["bash", "-c", script], env={**env, **changes},
            capture_output=True, text=True, timeout=5, check=False,
        )
        assert result.returncode == expected_rc, (changes, result.stderr)
        if marker:
            assert marker in result.stderr
        assert "SECRET_FIXTURE_NOT_LOGGABLE" not in (result.stdout + result.stderr)


def test_mcp_deploy_guards_precede_aws_assumption_and_remote_mutation():
    flow = FLOW.read_text(encoding="utf-8")
    assert "on:\n  workflow_dispatch:" in flow
    assert "github.actor == github.repository_owner" in flow
    assert "ref: ${{ github.sha }}" in flow
    assert "persist-credentials: false" in flow
    assert "cancel-in-progress: false" in flow
    before_aws = flow.index("MCP_DEPLOY_MAIN_MOVED_ABORT")
    oidc = flow.index("aws-actions/configure-aws-credentials@v4")
    before_ssm = flow.index("MCP_DEPLOY_PRE_SSM_MAIN_MOVED_ABORT")
    remote = flow.index("aws ssm send-command")
    assert before_aws < oidc < before_ssm < remote
    assert flow.count("GH_TOKEN: ${{ github.token }}") == 2
    assert "MCP_DEPLOY_MAIN_LOOKUP_BLOCKED" in flow
    assert "MCP_DEPLOY_PRE_SSM_MAIN_LOOKUP_BLOCKED" in flow
    assert "SOURCE_ARBITER_ADMISSION=ADMITTED" not in flow
    assert "LIVE_TRADE=YES" not in flow


def test_mcp_deploy_installer_has_bound_sha_before_restart_and_no_raw_logs():
    flow = FLOW.read_text(encoding="utf-8")
    assert 'sha256sum ops/aws/install_readonly_mcp.sh' in flow
    assert '[[ "$INSTALL_SHA" =~ ^[0-9a-f]{64}$ ]]' in flow
    assert "'$INSTALL_SHA' \\" in flow or "'$INSTALL_SHA' \"" in flow
    assert "sha256sum -c - >/dev/null" in flow
    assert flow.index("sha256sum -c - >/dev/null") < flow.index(
        "REPO_REF='$REPO_REF' REPAIR_CONTEXT_EVENT_SEQUENCE='$REPAIR_CONTEXT_EVENT_SEQUENCE' bash"
    )
    assert "--proto '=https' --tlsv1.2" in flow
    assert 'install.out" 2> "\\$stage/install.err' in flow
    assert "SSM_REMOTE_OUTPUT_GITHUB_LOG=WITHHELD" in flow
    assert "systemctl restart stock-razor-us-livefeed" not in flow
    assert "systemctl stop stock-razor-us-livefeed" not in flow


def test_mcp_deployment_remains_manual_and_does_not_silently_mutate():
    flow = FLOW.read_text(encoding="utf-8")
    assert "  workflow_dispatch:" in flow
    assert "issue_comment:" not in flow
    assert "schedule:" not in flow
    assert "repository_dispatch:" not in flow
    installer = Path("ops/aws/install_readonly_mcp.sh").read_text(encoding="utf-8")
    assert "systemctl restart" in installer
    assert 'assert result["live_trade"] is False' in installer
    assert 'assert result["radar_admission"] == "BLOCKED"' in installer
