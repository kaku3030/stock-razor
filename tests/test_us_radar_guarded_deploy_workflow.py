"""US Radar AWS deploy: consent, source identity, digest and SSM privacy.

Static + actual bash grammar checks. Tests NEVER dispatch AWS operations.
"""
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


WORKFLOW = Path(".github/workflows/deploy-us-radar-worker.yml")


def source():
    return WORKFLOW.read_text(encoding="utf-8")


def test_explicit_restart_consent_and_immutable_sha_before_any_aws_credentials():
    s = source()
    assert "approve_restart:" in s
    assert "default: false" in s
    assert "expected_main_sha:" in s
    assert "inputs.approve_restart == true" in s
    assert "inputs.expected_main_sha == github.sha" in s
    assert "github.ref == 'refs/heads/main'" in s
    assert "ref: ${{ github.sha }}" in s
    assert "persist-credentials: false" in s
    assert '[[ "$revision" == "$current_main" ]]' in s
    assert "git ls-remote origin refs/heads/main" in s
    assert s.index("US_RADAR_MAIN_MOVED_ABORT") < s.index(
        "aws-actions/configure-aws-credentials@"
    )
    assert s.index("PRIVATE_REPO_CLOUD_SOURCE_TRANSPORT_NOT_MIGRATED") < s.index(
        "aws-actions/configure-aws-credentials@"
    )


def test_scripts_are_hash_pinned_before_radar_restart_and_verification():
    s = source()
    assert 'install_sha=$(sha256sum ops/aws/install_us_radar_worker.sh' in s
    assert 'verify_sha=$(sha256sum ops/aws/verify_us_radar_worker.sh' in s
    assert s.count("sha256sum -c - >/dev/null") == 2
    assert 'INSTALL_SHA: "${{ steps.source.outputs.install_sha }}"' in s
    assert 'VERIFY_SHA: "${{ steps.source.outputs.verify_sha }}"' in s
    assert s.index("sha256sum -c - >/dev/null") < s.index(
        "REPO_REF='$REPO_REF' SOURCE_REPO_SHA='$SOURCE_REPO_SHA' bash"
    )
    assert "US_RADAR_ACCEPTANCE=FAILED" in s
    assert "US_RADAR_INSTALL=FAILED" in s
    assert "cancel-in-progress: false" in s


def test_no_raw_aws_invocation_or_radar_heartbeat_is_printed_to_actions():
    s = source()
    assert "aws ssm send-command" in s
    assert s.count('printf \'%s\\n\' "$inv"') == 0
    assert 'echo "$inv"' not in s
    assert 'echo "$out"' not in s
    assert 'cat "$status"' not in s
    assert "grep -Fx US_RADAR_WORKER_VERIFY=PASS" in s
    assert "grep -Fx RADAR_ADMISSION=BLOCKED" in s
    assert "grep -Fx LIVE_TRADE=NO" in s
    assert "US_RADAR_WORKER_AWS_DEPLOYMENT=PASS" in s


@pytest.mark.skipif(not shutil.which("bash"), reason="bash executable required")
def test_embedded_run_steps_parse_as_bash():
    wf = yaml.safe_load(source())
    steps = wf["jobs"]["deploy"]["steps"]
    run_steps = [step["run"] for step in steps if "run" in step]
    assert len(run_steps) == 4
    for code in run_steps:
        result = subprocess.run(
            ["bash", "-n"], input=code, text=True,
            capture_output=True, check=False, timeout=5
        )
        assert result.returncode == 0, result.stderr[:500]


def test_worker_deploy_is_inert_without_operator_dispatch():
    s = source()
    assert "workflow_dispatch:" in s
    assert "schedule:" not in s
    assert "push:" not in s
    assert "approve_restart == true" in s
    assert "SOURCE_REPO_SHA" in s
