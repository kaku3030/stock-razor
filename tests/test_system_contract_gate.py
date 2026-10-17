"""Exercise the real CI shell entrypoint: failed contracts must fail the gate."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _bash():
    executable = shutil.which("bash")
    if os.name == "nt":
        # Use Git Bash rather than the Windows WSL launcher.
        git = shutil.which("git")
        candidate = Path(git).resolve().parent.parent / "bin" / "bash.exe" if git else None
        executable = str(candidate) if candidate and candidate.is_file() else None
    if not executable:
        pytest.skip("Bash is required to exercise the CI entrypoint")
    return executable


@pytest.mark.parametrize("phase,expected", [("system-contracts", 17), ("unknown-phase", 2)])
def test_system_contract_command_propagates_failure_before_any_promotion(tmp_path, phase, expected):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    invoked = tmp_path / "python-args.txt"
    stub = bin_dir / "python"
    stub.write_text(
        '#!/bin/sh\nprintf "%s\n" "$@" > "$CONTRACT_ARGS"\nexit 17\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
           "CONTRACT_ARGS": invoked.as_posix()}
    result = subprocess.run(
        [_bash(), "scripts/ci_gate.sh", phase], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    if phase == "unknown-phase":
        assert not invoked.exists()
        return
    args = invoked.read_text(encoding="utf-8").splitlines()
    assert args[:5] == ["-X", "utf8", "-m", "pytest", "-q"]
    assert args[args.index("-m", 3) + 1] == "not network"
    # Guard distinct failure boundaries, including stale/partial data and PIT,
    # rather than accepting a green gate that only ran shape/smoke tests.
    assert set(args) >= {
        "tests/test_market_data_quality_invariants.py",
        "tests/test_cn_tickflow_research_cache.py",
        "tests/test_futu_k1m_closure_pipeline.py",
        "tests/test_us_canonical_runtime_reader.py",
        "tests/test_closed_bar_paper_replay.py",
        "tests/test_paper_execution_admission.py",
        "tests/test_cloud_runtime_evidence.py",
        "tests/test_engineering_autonomy_loop.py",
        "tests/test_provider_billing_renewal_watch.py",
    }
