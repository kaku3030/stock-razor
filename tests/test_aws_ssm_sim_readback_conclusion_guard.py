"""Exercise the public-safe conclusion guard against synthetic AWS readbacks.

This executes ONLY local jq evaluation, not OpenD, SSM, or market-data IO.
"""

from pathlib import Path
import json
import shutil
import subprocess

import pytest


WORKFLOW = Path(__file__).resolve().parents[1] / (
    ".github/workflows/aws-ssm-sim-account-discovery.yml"
)
SHA = "a" * 40


def _guard() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    anchor = """if ! jq -en --argjson v "$safe" --arg sha "$SOURCE_SHA" '"""
    assert anchor in text
    start = text.index(anchor) + len(anchor)
    end = text.index("' >/dev/null; then", start)
    return text[start:end]


def _valid_readback() -> dict:
    return {
        "probe": "us_opend_sim_account_discovery_v0_1",
        "source_revision": SHA,
        "observed_at_utc": "2026-10-11T11:29:17+00:00",
        "query_status": "PASS",
        "opend_reachable": True,
        "simulated_us_account_count": 1,
        "account_evidence": "OBSERVED_NOT_VERIFIED",
        "balance_readback": "PASS",
        "positions_readback": "PASS",
        "orders_readback": "PASS",
        "history_readback": "PASS",
        "position_review": "REQUIRED",
        "order_review": "NOT_REQUIRED",
        "sim_native_fills": "UNSUPPORTED_BY_OPEND",
        "paper_preflight": "BLOCKED",
        "paper_auto_ready": False,
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": False,
    }


def _passes(data: dict) -> bool:
    result = subprocess.run(
        [
            "jq", "-e", "-n", "--argjson", "v", json.dumps(data),
            "--arg", "sha", SHA, _guard(),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq executable absent")
def test_success_only_with_exact_complete_us_sim_readbacks():
    valid = _valid_readback()
    assert _passes(valid)
    valid["position_review"] = "NOT_REQUIRED"
    valid["order_review"] = "REQUIRED"
    assert _passes(valid)


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq executable absent")
@pytest.mark.parametrize(
    "key,bad_value",
    [
        ("probe", "other"),
        ("source_revision", "b" * 40),
        ("observed_at_utc", "UNKNOWN"),
        ("query_status", "ERROR"),
        ("opend_reachable", False),
        ("simulated_us_account_count", 0),
        ("simulated_us_account_count", 2),
        ("simulated_us_account_count", True),
        ("account_evidence", "BLOCKED_NO_US_SIMULATE_ROWS"),
        ("balance_readback", "UNAVAILABLE"),
        ("positions_readback", "ERROR"),
        ("orders_readback", "NOT_RUN"),
        ("history_readback", "INVALID"),
        ("position_review", "UNKNOWN"),
        ("order_review", "UNKNOWN"),
        ("sim_native_fills", "PASS"),
        ("paper_preflight", "PASS"),
        ("paper_auto_ready", True),
        ("radar_admission", "PASS"),
        ("source_arbiter_admission", "PASS"),
        ("live_trade", True),
    ],
)
def test_any_missing_false_or_inconsistent_readback_fails_closed(key, bad_value):
    example = _valid_readback()
    example[key] = bad_value
    assert not _passes(example)


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq executable absent")
def test_malformed_or_missing_summary_keys_cannot_create_green_job():
    for key in _valid_readback():
        example = _valid_readback()
        del example[key]
        assert not _passes(example)


def test_conclusion_guard_only_emits_finite_public_status_and_no_orders():
    src = WORKFLOW.read_text(encoding="utf-8")
    assert 'echo "SIM_ACCOUNT_DISCOVERY_SUMMARY=$safe"' in src
    assert 'echo "SIM_READBACK=BLOCKED_OR_INCOMPLETE"' in src
    assert 'echo "SIM_READBACK=PASS_PAPER_BLOCKED"' in src
    assert 'SIM_READBACK=PASS_PAPER_BLOCKED' not in _guard()
    assert "place_order(" not in src
    assert "unlock_trade(" not in src
    assert "modify_order(" not in src
    assert "LIVE_TRADE=NO" in src
