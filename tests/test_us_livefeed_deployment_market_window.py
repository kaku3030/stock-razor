"""No-network guard tests for the 2026-10-12 correlated US K1M outage."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.guard_us_livefeed_restart_window import (
    classify_us_livefeed_restart_window,
)

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "ops/aws/install_us_opend_livefeed.sh"
WORKFLOW = ROOT / ".github/workflows/deploy-us-opend-livefeed.yml"


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    (
        ("2026-10-12T14:58:39+00:00", "US_SESSION_SAFETY_WINDOW_BLOCKED"),
        ("2026-10-12T14:59:21+00:00", "US_SESSION_SAFETY_WINDOW_BLOCKED"),
        ("2026-10-12T13:00:00+00:00", "US_SESSION_SAFETY_WINDOW_BLOCKED"),
        ("2026-10-12T20:29:59+00:00", "US_SESSION_SAFETY_WINDOW_BLOCKED"),
        ("2026-10-12T20:30:00+00:00", "SAFE_OFF_WINDOW"),
        ("2026-10-12T12:59:59+00:00", "SAFE_OFF_WINDOW"),
        ("2026-12-14T14:30:00+00:00", "US_SESSION_SAFETY_WINDOW_BLOCKED"),
        ("2026-12-14T21:29:59+00:00", "US_SESSION_SAFETY_WINDOW_BLOCKED"),
        ("2026-12-14T21:30:00+00:00", "SAFE_OFF_WINDOW"),
        ("2026-10-17T14:58:39+00:00", "SAFE_OFF_WINDOW"),
    ),
)
def test_us_restart_safety_window_handles_dst_and_deploy_incident(timestamp, expected):
    instant = datetime.fromisoformat(timestamp)
    assert classify_us_livefeed_restart_window(instant) == expected


@pytest.mark.parametrize("clock", (None, "2026-10-12T14:58:39+00:00", True, 1,
                                   datetime(2026, 10, 12, 14, 58)))
def test_clock_cannot_be_untrusted_or_naive(clock):
    assert classify_us_livefeed_restart_window(clock) == "CLOCK_UNKNOWN_BLOCKED"


def test_aws_workflow_guard_runs_before_any_aws_oidc():
    source = WORKFLOW.read_text(encoding="utf-8")
    marker = "python3 scripts/guard_us_livefeed_restart_window.py"
    assert source.count(marker) == 1
    assert source.index(marker) < source.index("aws-actions/configure-aws-credentials@v4")
    assert "inputs.approve_restart == true" in source
    assert "inputs.expected_main_sha == github.sha" in source


def test_ec2_safety_gate_precedes_repository_mutation_and_rechecks_restart():
    source = INSTALLER.read_text(encoding="utf-8")
    assert source.count("require_safe_us_restart_window") == 3
    assert source.index("require_safe_us_restart_window\ninstall -d") < source.index("git -C \"$INSTALL_ROOT/repo\" fetch")
    assert source.index("require_safe_us_restart_window\nsystemctl restart") < source.index("systemctl restart \"$SERVICE_NAME\"")
    assert "ZoneInfo(\"America/New_York\")" in source
    assert "time(9, 0)" in source and "time(16, 30)" in source
    assert "US_SESSION_SAFETY_WINDOW_BLOCKED" in source
    assert "CLOCK_UNKNOWN_BLOCKED" in source
    assert "systemctl restart \"$SERVICE_NAME\"" in source
