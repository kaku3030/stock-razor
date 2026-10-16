"""Contract guards for the read-only Paper SSM qualification workflow."""

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/qualify-paper-runtime-ssm-readonly.yml"


def test_workflow_is_fixed_target_oidc_and_closed_by_default():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "id-token: write" in text
    assert "contents: read" in text
    assert "role-to-assume: arn:aws:iam::888425712426:role/StockRazorGitHubOpsRole" in text
    assert 'TARGET_INSTANCE_ID: i-01738342af3efac72' in text
    assert 'PAPER_AUTO_READY: "NO"' in text
    assert "RADAR_ADMISSION: BLOCKED" in text
    assert "SOURCE_ARBITER_ADMISSION: BLOCKED" in text
    assert 'LIVE_TRADE: "NO"' in text
    assert 'TRADE_EXECUTION: "NO"' in text


def test_workflow_has_no_mutation_or_order_capability():
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "systemctl start", "systemctl stop", "systemctl restart",
        "aws-actions/configure-aws-credentials@",  # checked separately below
        "GetSecretValue", "broker.place", "create_paper_adapter",
        "paper-order-", "provider.connect", "OpenD",
    ):
        if forbidden == "aws-actions/configure-aws-credentials@":
            continue
        assert forbidden not in text
    assert "aws ssm send-command" in text
    assert "SSM_PROBE_ORDER_ACTIONS NONE" in text
    assert "PAPER_EXTERNAL_TRADING_ACTIVITY NOT_VERIFIED" in text
    assert "grep -E '^(PAPER_|SSM_PROBE_|RAW_RUNTIME_)'" in text
    assert "PAPER_EXTERNAL_BROKER_ORDERS" not in text
    assert "PAPER_SIMULATED_ORDERS" not in text
    assert "PAPER_RESTART_RECOVERY UNVERIFIED" in text


def test_schedule_probe_uses_controlled_config_without_process_environment():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "/proc/" not in text
    assert "environ" not in text
    assert 'systemctl show "$unit" -p ExecStart --value' in text
    assert '"$working/.env"' in text
    assert "SCHEDULE_TIMES" in text
    assert "PAPER_HALF_HOUR_SCHEDULE UNKNOWN" in text


def test_order_activity_is_not_claimed_from_a_read_only_probe():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "runtime orders were not inspected" in text
    assert "PAPER_EXTERNAL_TRADING_ACTIVITY=(YES|true|PASS)" in text
    assert "External trading activity: NOT_VERIFIED" in text


def test_workflow_withholds_raw_runtime_output_and_checks_exact_main():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "persist-credentials: false" in text
    assert "git rev-parse HEAD" in text
    assert "git/ref/heads/main" in text
    assert "PAPER_RUNTIME_SHA PASS" in text
    assert "EXPECTED_RUNTIME_SHA_PLACEHOLDER" in text
    assert "RAW_RUNTIME_OUTPUT_WITHHELD YES" in text
    assert "SecretString: NOT_READ" in text



def _run_embedded_schedule_probe(tmp_path, raw_env: str) -> str:
    """Exercise the exact SSM embedded config parser without AWS or secrets."""
    import subprocess
    import sys
    import textwrap

    text = WORKFLOW.read_text(encoding="utf-8")
    marker = '/usr/bin/python3 - "$working/.env" <<\'PY\''
    assert text.count(marker) == 1
    snippet = text.split(marker, 1)[1].split("\n          PY", 1)[0]
    code = textwrap.dedent(snippet)
    config = tmp_path / "fake.env"
    config.write_text(raw_env, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", code, str(config)],
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_halfhour_ssm_probe_requires_all_48_distinct_slots(tmp_path):
    grid = ",".join(
        f"{hour:02d}:{minute:02d}"
        for hour in range(24) for minute in (0, 30)
    )
    good = _run_embedded_schedule_probe(tmp_path, "SCHEDULE_TIMES=" + grid + "\n")
    assert good == "PAPER_HALF_HOUR_SCHEDULE CONFIGURED_48_SLOTS_ONLY"

    # Existing code incorrectly claimed PASS for one 09:00 or just 09:00/09:30.
    for raw in (
        "SCHEDULE_TIME=09:00\n",
        "SCHEDULE_TIMES=09:00,09:30\n",
        "SCHEDULE_TIMES=" + grid.replace("23:30", "23:00") + "\n",
        "SCHEDULE_TIMES=" + grid.replace("23:30", "") + "\n",
        "SCHEDULE_TIMES=09:01,09:30\n",
    ):
        assert _run_embedded_schedule_probe(tmp_path, raw) == (
            "PAPER_HALF_HOUR_SCHEDULE UNKNOWN"
        )


def test_full_config_grid_does_not_claim_service_trigger_execution(tmp_path):
    all_slots = ",".join(
        f"{hour:02d}:{minute:02d}"
        for hour in range(24) for minute in (0, 30)
    )
    outcome = _run_embedded_schedule_probe(
        tmp_path, "OTHER_SECRET_SHOULD_NOT_LEAK=not-for-output\n"
        + "SCHEDULE_TIMES=" + all_slots + "\n"
    )
    assert outcome == "PAPER_HALF_HOUR_SCHEDULE CONFIGURED_48_SLOTS_ONLY"
    assert "PASS" not in outcome
    assert "not-for-output" not in outcome

def test_paper_heartbeat_future_mtime_is_not_fresh(tmp_path):
    """A future-dated heartbeat must never be treated as fresh by the SSM probe."""
    import json
    import os
    import subprocess
    import sys
    import textwrap
    import time

    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = '/usr/bin/python3 - "$status_path" <<\'PY\''
    assert workflow.count(marker) == 1
    snippet = workflow.split(marker, 1)[1].split("\n          PY", 1)[0]
    code = textwrap.dedent(snippet)
    heartbeat = tmp_path / "latest-heartbeat.json"
    heartbeat.write_text(json.dumps({
        "live_trade": False,
        "trade_execution": False,
        "paper_auto_ready": False,
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
    }), encoding="utf-8")
    now = time.time()
    for age_seconds, expected in (
        (30, "PASS"),
        (-3600, "UNKNOWN"),
        (1200, "UNKNOWN"),
    ):
        stamped = now - age_seconds
        os.utime(heartbeat, (stamped, stamped))
        process = subprocess.run(
            [sys.executable, "-c", code, str(heartbeat)],
            capture_output=True, text=True, check=False, timeout=5,
        )
        assert process.returncode == 0, process.stderr
        assert "PAPER_HEARTBEAT_SCHEMA=PASS" in process.stdout
        assert "PAPER_RUNTIME_GATES_CLOSED=PASS" in process.stdout
        assert f"PAPER_HEARTBEAT_FRESHNESS={expected}" in process.stdout


def _run_ssm_core_readback_gate(tmp_path, rows):
    """Execute the same bounded status gate used after the SSM capture."""
    import subprocess
    import textwrap

    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = "          # Fail closed: SSM transport success is not runtime qualification."
    assert workflow.count(marker) == 1
    source = workflow.split(marker, 1)[1].split(
        "\n      - name: Emit bounded qualification summary", 1,
    )[0]
    code = "set -euo pipefail\n" + textwrap.dedent(source)
    (tmp_path / "qualification.txt").write_text(
        "\n".join(rows) + "\n", encoding="utf-8",
    )
    return subprocess.run(
        ["bash", "-c", code], cwd=tmp_path, capture_output=True,
        text=True, check=False, timeout=5,
    )


def test_paper_runtime_ssm_gate_distinguishes_transport_from_readback(tmp_path):
    required = (
        "PAPER_UNIT_ACTIVE", "PAPER_RUNTIME_SHA", "PAPER_HEARTBEAT_SCHEMA",
        "PAPER_RUNTIME_GATES_CLOSED", "PAPER_HEARTBEAT_FRESHNESS",
    )
    good = [f"{key}=PASS" for key in required]
    verified = _run_ssm_core_readback_gate(tmp_path, good)
    assert verified.returncode == 0, verified.stderr
    assert "PAPER_RUNTIME_QUALIFICATION=CORE_READBACK_ONLY" in verified.stdout
    assert "PAPER_AUTO_READY=YES" not in verified.stdout

    # SSM returned safely, but the deployed runtime is absent or stale.
    for bad in (
        ["PAPER_UNIT_ACTIVE=UNKNOWN", *good[1:]],
        [*good[:2], "PAPER_HEARTBEAT_SCHEMA=UNKNOWN", *good[3:]],
        [*good[:4], "PAPER_HEARTBEAT_FRESHNESS=UNKNOWN"],
        good[:-1],
        [*good, "PAPER_RUNTIME_SHA=UNKNOWN"],
    ):
        result = _run_ssm_core_readback_gate(tmp_path, bad)
        assert result.returncode != 0
        assert "PAPER_RUNTIME_QUALIFICATION=BLOCKED" in result.stdout
        assert "CORE_READBACK_ONLY" not in result.stdout


def test_paper_runtime_sha_probe_accepts_git_linked_worktree(tmp_path):
    """Execute the workflow's POSIX condition against real local Git layouts."""
    import os
    import subprocess

    def git(*args):
        return subprocess.run(
            ["git", *map(str, args)],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()

    root = tmp_path / "checkout"
    root.mkdir()
    git("-C", root, "init", "-q")
    (root / "README").write_text("paper probe fixture\n", encoding="utf-8")
    git("-C", root, "add", "README")
    git(
        "-C", root, "-c", "user.name=Test",
        "-c", "user.email=test@example.invalid",
        "commit", "-qm", "initial",
    )
    exact_sha = git("-C", root, "rev-parse", "HEAD")
    linked = tmp_path / "linked"
    git("-C", root, "worktree", "add", "-q", "-b", "paper-check", linked)
    assert (root / ".git").is_dir()
    assert (linked / ".git").is_file()

    workflow = WORKFLOW.read_text(encoding="utf-8")
    lines = [
        line.strip() for line in workflow.splitlines()
        if line.strip().startswith('if test -d "$working"')
    ]
    assert len(lines) == 1
    assert lines[0].endswith("; then")
    condition = lines[0][3:-6]

    def probe(working, sha):
        return subprocess.run(
            ["sh", "-c", condition],
            env={**os.environ, "working": str(working), "expected_sha": sha},
            capture_output=True, text=True, check=False, timeout=5,
        ).returncode

    assert probe(root, exact_sha) == 0
    assert probe(linked, exact_sha) == 0
    assert probe(linked, "0" * 40) != 0
    assert probe(tmp_path / "not-a-git-dir", exact_sha) != 0
