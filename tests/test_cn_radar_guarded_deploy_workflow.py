"""Execute CN Radar source/evidence gates with local tools; never access AWS."""
import hashlib
import os
from pathlib import Path
import subprocess

import pytest
import yaml


FLOW = Path(".github/workflows/deploy-cn-radar-worker.yml")
SHA = "a" * 40


def steps():
    return yaml.safe_load(FLOW.read_text())["jobs"]["deploy"]["steps"]


def run(code, env, *, cwd=None):
    return subprocess.run(["bash", "-eu", "-c", code], env={**os.environ, "SOURCE_PROVIDER": "eastmoney", **env},
                          cwd=cwd, text=True, capture_output=True, timeout=5)


def executable(path, code):
    path.write_text("#!/bin/bash\n" + code)
    path.chmod(0o755)


def test_workflow_gates_and_all_embedded_shell_grammar():
    doc = yaml.safe_load(FLOW.read_text())
    trigger = doc.get("on", doc.get(True))
    assert set(trigger) == {"workflow_dispatch"}
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert inputs["approve_restart"]["default"] is False
    condition = doc["jobs"]["deploy"]["if"]
    assert "github.actor == github.repository_owner" in condition
    assert "inputs.approve_restart == true" in condition
    assert "inputs.expected_main_sha == github.sha" in condition
    assert doc["concurrency"]["cancel-in-progress"] is False
    assert doc["permissions"] == {"contents": "read", "id-token": "write"}
    source_index = next(i for i, s in enumerate(steps()) if s.get("id") == "source")
    aws_index = next(i for i, s in enumerate(steps()) if "configure-aws-credentials" in s.get("uses", ""))
    assert source_index < aws_index
    checkout = next(s for s in steps() if "checkout@" in s.get("uses", ""))
    assert checkout["with"] == {"ref": "${{ github.sha }}", "persist-credentials": False}
    for step in steps():
        if "run" in step:
            checked = subprocess.run(["bash", "-n"], input=step["run"],
                                     text=True, capture_output=True, timeout=5)
            assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize("checkout,main,expected,private,passes", [
    (SHA, SHA, SHA, "false", True),
    ("b" * 40, SHA, SHA, "false", False),
    (SHA, "b" * 40, SHA, "false", False),
    (SHA, SHA, "b" * 40, "false", False),
    ("malformed", SHA, SHA, "false", False),
    (SHA, SHA, SHA, "true", False),
])
def test_source_gate_rejects_moved_or_unbound_source(tmp_path, checkout, main, expected, private, passes):
    executable(tmp_path / "git", 'if [ "$1" = rev-parse ]; then printf "%s\\n" "$MOCK_CHECKOUT"; else printf "%s refs/heads/main\\n" "$MOCK_MAIN"; fi\n')
    code = next(s["run"] for s in steps() if s.get("id") == "source")
    code = code.replace("${{ github.sha }}", SHA).replace("${{ github.event.repository.private }}", private)
    result = run(code, {"PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                        "MOCK_CHECKOUT": checkout, "MOCK_MAIN": main,
                        "EXPECTED_SHA": expected, "GITHUB_OUTPUT": str(tmp_path / "output")})
    assert (result.returncode == 0) is passes


def test_main_moving_after_oidc_prevents_ssm_dispatch(tmp_path):
    executable(tmp_path / "gh", 'printf "%s\\n" "$MOCK_MAIN"\n')
    executable(tmp_path / "aws", 'touch "$AWS_MARKER"\nexit 99\n')
    code = next(s["run"] for s in steps() if s.get("id") == "deploy")
    marker = tmp_path / "aws-called"
    result = run(code, {"PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                        "REPO_REF": SHA, "MOCK_MAIN": "b" * 40,
                        "INSTALL_SHA": "c" * 64, "VERIFY_SHA": "d" * 64, "DEPLOY_SHA": "e" * 64,
                        "GITHUB_REPOSITORY": "fixture/repo", "AWS_MARKER": str(marker)})
    assert result.returncode == 2
    assert "CN_RADAR_PRE_SSM_MAIN_MOVED_ABORT" in result.stderr
    assert not marker.exists()


@pytest.mark.parametrize("tamper", [None, "install", "verify"])
def test_both_download_hashes_verify_before_install_and_logs_stay_private(tmp_path, tamper):
    install = 'test "$SOURCE_PROVIDER" = tickflow\n' + 'touch "$INSTALL_MARKER"\necho PRIVATE_CANARY\n'
    verify = 'test "$2" = tickflow\n' + 'printf "%s\\n" PRIVATE_CANARY enabled active CN_RADAR_WORKER_VERIFY=PASS RADAR_ADMISSION=BLOCKED LIVE_TRADE=NO\n'
    install_path = tmp_path / "install-source"
    verify_path = tmp_path / "verify-source"
    install_path.write_text(install)
    verify_path.write_text(verify)
    hashes = {"install": hashlib.sha256(install.encode()).hexdigest(),
              "verify": hashlib.sha256(verify.encode()).hexdigest()}
    if tamper:
        (install_path if tamper == "install" else verify_path).write_text("echo PRIVATE_CANARY\n")
    executable(tmp_path / "curl", 'for arg in "$@"; do case "$arg" in *install_cn_radar_worker.sh) source="$INSTALL_SOURCE";; *verify_cn_radar_worker.sh) source="$VERIFY_SOURCE";; esac; done\nfor arg in "$@"; do target="$arg"; done\ncp "$source" "$target"\n')
    remote = Path("ops/aws/deploy_cn_radar_remote.sh").read_text(encoding="utf-8")
    marker = tmp_path / "installed"
    result = run(remote, {"PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                          "SOURCE_PROVIDER": "tickflow", "REPO_REF": SHA,
                          "INSTALL_SHA": hashes["install"], "VERIFY_SHA": hashes["verify"],
                          "INSTALL_SOURCE": str(install_path), "VERIFY_SOURCE": str(verify_path),
                          "INSTALL_MARKER": str(marker)})
    assert (result.returncode == 0) is (tamper is None)
    assert marker.exists() is (tamper is None)
    assert "PRIVATE_CANARY" not in result.stdout + result.stderr


@pytest.mark.parametrize("status,proof,passes", [
    ("Success", "CN_RADAR_WORKER_AWS_DEPLOYMENT=PASS\nRADAR_ADMISSION=BLOCKED\nLIVE_TRADE=NO\n", True),
    ("Success", "CN_RADAR_WORKER_AWS_DEPLOYMENT=PASS\nLIVE_TRADE=NO\n", False),
    ("Success", "CN_RADAR_WORKER_AWS_DEPLOYMENT=PASS PRIVATE_CANARY\nRADAR_ADMISSION=BLOCKED\nLIVE_TRADE=NO\n", False),
    ("Failed", "", False),
    ("TimedOut", "", False),
])
def test_wait_step_requires_exact_proof_without_mirroring_ssm_content(status, proof, passes):
    code = steps()[-1]["run"]
    fake = 'aws(){ case "$*" in *"--query Status"*) printf "%s" "$MOCK_STATUS";; *) printf "%s" "$MOCK_OUTPUT";; esac; }; export -f aws\n'
    result = run(fake + code, {"MOCK_STATUS": status, "MOCK_OUTPUT": "PRIVATE_CANARY\n" + proof,
                              "COMMAND_ID": "fixture", "TARGET_INSTANCE_ID": "fixture"})
    assert (result.returncode == 0) is passes
    assert "PRIVATE_CANARY" not in result.stdout + result.stderr
    if not passes:
        assert "CN_RADAR_WORKER_AWS_DEPLOYMENT=PASS" not in result.stdout
