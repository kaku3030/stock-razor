"""Exercise real SSM POSIX bootstrap templates without AWS, keys or providers."""
from __future__ import annotations

import base64
import gzip
from hashlib import sha256
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
ISOLATED = ROOT / ".github/workflows/probe-tickflow-aws-isolated.yml"
PREMIUM = ROOT / ".github/workflows/probe-tickflow-aws-premium.yml"
BOOTSTRAP_PATHS = {
    "isolated": "ops/aws/run_tickflow_cloud_isolated_smoke.sh",
    "premium": "ops/aws/run_tickflow_premium_probe.sh",
}


def _remote_template(workflow: str) -> str:
    marker = "read -r -d '' remote <<REMOTE || true\n"
    assert marker in workflow
    content = workflow.split(marker, 1)[1].split("\n          REMOTE", 1)[0]
    return "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in content.splitlines()
    ).replace("\\$", "$")


@pytest.mark.parametrize("lane,workflow_path", [
    ("isolated", ISOLATED),
    ("premium", PREMIUM),
])
def test_checksummed_ssm_bootstrap_runs_exact_source_and_rejects_tampering(
    lane, workflow_path
):
    if not all(shutil.which(cmd) for cmd in ("sh", "gzip", "sha256sum", "base64")):
        pytest.skip("POSIX-sh and source-transfer binaries required")
    workflow = workflow_path.read_text(encoding="utf-8")
    source = b"#!/bin/sh\necho SYNTHETIC_TICKFLOW_BOOTSTRAP=PASS\n"
    digest = sha256(source).hexdigest()
    payload = base64.b64encode(gzip.compress(source, mtime=0)).decode("ascii")
    remote = _remote_template(workflow)
    assert 'sha256sum -c - >/dev/null' in remote
    assert remote.index("sha256sum -c -") < remote.index('bash "$temp_dir/bootstrap.sh"')
    assert "set -eu" in remote
    assert "umask 077" in remote
    remote = remote.replace("$bootstrap_payload", payload)
    remote = remote.replace("$bootstrap_hash", digest)
    # The synthetic fixture must NEVER execute the actual network / paid
    # bootstrap. Replace only the terminal invocation after the hash check.
    remote, count = re.subn(
        r'(?m)^bash "\$temp_dir/bootstrap\.sh".*$',
        'sh "$temp_dir/bootstrap.sh"',
        remote,
    )
    assert count == 1

    success = subprocess.run(
        ["sh", "-c", remote], text=True, capture_output=True, timeout=12
    )
    assert success.returncode == 0, success.stderr
    assert "SYNTHETIC_TICKFLOW_BOOTSTRAP=PASS" in success.stdout
    failure = subprocess.run(
        ["sh", "-c", remote.replace(digest, "0" * 64)],
        text=True, capture_output=True, timeout=12,
    )
    assert failure.returncode != 0
    assert "SYNTHETIC_TICKFLOW_BOOTSTRAP=PASS" not in failure.stdout


def test_isolated_manual_probe_uses_exact_checkout_and_safe_status_projection():
    workflow = ISOLATED.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert '[[ "$script_sha" == "${{ github.sha }}" ]]' in workflow
    assert "gzip -n -9 -c ops/aws/run_tickflow_cloud_isolated_smoke.sh | base64 -w0" in workflow
    assert "TICKFLOW_ISOLATED_SSM_PAYLOAD_TOO_LARGE" in workflow
    assert "TICKFLOW_ISOLATED_SANITIZED=" in workflow
    assert "EXPECTED_REVISION=\"$script_sha\"" in workflow
    assert "raw.githubusercontent.com" not in workflow
    assert "curl --fail" not in workflow
    assert "print(json.dumps(data,sort_keys=True))" not in workflow
    assert "LIVE_TRADE=NO" in workflow
    assert "systemctl restart" not in workflow


def test_premium_manual_probe_bounds_success_output_and_retains_diagnostics():
    workflow = PREMIUM.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "default: false" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert '[[ "$revision" == "${{ github.sha }}" ]]' in workflow
    assert "gzip -n -9 -c ops/aws/run_tickflow_premium_probe.sh | base64 -w0" in workflow
    assert "TICKFLOW_PREMIUM_SSM_PAYLOAD_TOO_LARGE" in workflow
    assert "bootstrap_stage=VERIFY_BOOTSTRAP_HASH" in workflow
    assert "TICKFLOW_PREMIUM_SANITIZED=" in workflow
    assert "EXPECTED_REVISION=\"$revision\"" in workflow
    assert "TICKFLOW_PREMIUM_FAILED_STAGE=SSM_REMOTE_COMMAND" in workflow
    assert "TICKFLOW_PREMIUM_SECRET_ERROR_CLASS=" in workflow
    assert "raw.githubusercontent.com" not in workflow
    assert "curl --fail" not in workflow
    assert 'Success) aws ssm get-command-invocation' not in workflow
    assert 'echo "$output"' not in workflow
    assert "TICKFLOW_API_KEY" not in workflow
    assert "LIVE_TRADE=NO" in workflow or "live_trade\" is False" in workflow
    assert "systemctl restart" not in workflow


def test_remaining_nested_public_fetches_are_not_misreported_private_ready():
    # Shipping the *outer* bootstrap is not full authenticated private
    # distribution: the bootstraps still fetch and hash exact GitHub sources.
    assert "raw.githubusercontent.com" in (
        ROOT / BOOTSTRAP_PATHS["isolated"]
    ).read_text(encoding="utf-8")
    assert "raw.githubusercontent.com" in (
        ROOT / BOOTSTRAP_PATHS["premium"]
    ).read_text(encoding="utf-8")
