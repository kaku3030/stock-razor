"""Guardrails for manual AWS US OpenD deployment: zero cloud activity in CI."""
from pathlib import Path
import re
import shutil
import subprocess
import textwrap

import pytest


WORKFLOW = Path(".github/workflows/deploy-us-opend-livefeed.yml")


def _source():
    return WORKFLOW.read_text(encoding="utf-8")


def _shell_blocks():
    source = _source()
    # Extract multiline 'run' scripts at the workflow step indentation only.
    blocks = re.findall(
        r"(?m)^        run: \|\n((?:(?:^          [^\n]*\n)|(?:^\n))+)",
        source,
    )
    assert len(blocks) == 4
    return tuple(textwrap.dedent(block) for block in blocks)


def test_deploy_requires_manual_restart_ack_and_exact_main_sha():
    source = _source()
    assert "workflow_dispatch:" in source
    assert "approve_restart:" in source
    assert "default: false" in source
    assert "expected_main_sha:" in source
    assert "inputs.approve_restart == true" in source
    assert "inputs.expected_main_sha == github.sha" in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "ref: ${{ github.sha }}" in source
    assert "persist-credentials: false" in source
    assert "ref: main" not in source
    assert "git ls-remote origin refs/heads/main" in source
    assert '[[ "$revision" == "$current_main" ]]' in source


def test_provider_files_sha256_verified_before_any_restart():
    source = _source()
    assert 'INSTALL_SHA: ${{ steps.source.outputs.install_sha }}' in source
    assert 'VERIFY_SHA: ${{ steps.source.outputs.verify_sha }}' in source
    assert source.count("sha256sum -c - >/dev/null") == 2
    assert source.count("raw.githubusercontent.com/kaku3030/stock-razor/$REPO_REF/") == 2
    assert source.index('printf \'%s  %s\\n\' \'$VERIFY_SHA\'') < source.index(
        "REPO_REF='$REPO_REF' STOCK_RAZOR_AB_BLEND_SUBSCRIBE='$AB_BLEND_SUBSCRIBE' bash"
    )
    assert "systemctl restart" not in source
    assert "aws ssm send-command" in source
    assert "--timeout-seconds 600" in source
    assert "cancel-in-progress: false" in source


def test_never_expose_broker_heartbeat_or_raw_ssm_response_to_actions():
    source = _source()
    assert '"$stage/install.log"' not in source  # remote uses escaped path
    assert 'install.log' in source and 'verify.log' in source
    assert 'printf \'%s\\n\' "$inv"' not in source
    assert "get-command-invocation" in source
    assert "StandardOutputContent" in source
    assert "--query StandardErrorContent" not in source
    assert 'echo "$out"' not in source
    assert 'printf \'%s\\n\' "$out"' not in source
    assert "US_OPEND_LIVEFEED_AWS_DEPLOYMENT=PASS" in source
    assert "RADAR_ADMISSION=BLOCKED" in source
    assert "LIVE_TRADE=NO" in source
    assert "CANONICAL_SNAPSHOT_EXPORT=PASS" in source
    assert 'grep -Fx CANONICAL_SNAPSHOT_EXPORT=PASS' in source
    assert "cat $status" not in source
    assert "source_arbiter_admission" not in source.lower() or (
        "SOURCE_ARBITER_ADMISSION=BLOCKED" in source
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_all_embedded_github_actions_scripts_have_valid_bash_syntax():
    for script in _shell_blocks():
        completed = subprocess.run(
            ["bash", "-n"], input=script, text=True,
            capture_output=True, timeout=5, check=False,
        )
        assert completed.returncode == 0, completed.stderr[:500]


def test_only_explicit_approval_can_schedule_service_restart():
    source = _source()
    assert "if: ${{ github.ref == 'refs/heads/main'" in source
    assert "approve_restart == true" in source
    assert "REPO_REF='$REPO_REF' STOCK_RAZOR_AB_BLEND_SUBSCRIBE='$AB_BLEND_SUBSCRIBE' bash" in source
    assert "install.err" in source
    assert "verify.err" in source
    assert "US_LIVEFEED_ACCEPTANCE=FAILED" in source
    assert "US_LIVEFEED_INSTALL=FAILED" in source
