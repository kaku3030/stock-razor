"""Synthetic-only private/public TickFlow Kline structure evidence regression.

No AWS, provider credentials, APIs, quote values, market orders or disk writes
outside a temporary redacted fixture. Field and time evidence is NOT admission.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

BOOTSTRAP = Path("ops/aws/run_tickflow_premium_probe.sh")
WORKFLOW = Path(".github/workflows/probe-tickflow-aws-premium.yml")
SHA = "b" * 40


def _run_private_sanitizer(tmp_path, ops):
    shell = BOOTSTRAP.read_text(encoding="utf-8")
    marker = 'TICKFLOW_ONE_QUOTE_SCOPE="$quote_only" python3 -c \'\n'
    end = "\n'\nprobe_stage=COMPLETE"
    assert shell.count(marker) == shell.count(end) == 1
    script = shell.split(marker, 1)[1].split(end, 1)[0]
    compile(script, "premium-private-sanitizer", "exec")
    fake = {
        "mode": "premium", "api_key_present": True,
        "request_scope": "STANDARD_ISOLATED_PROBE",
        "canonical_write": False, "order_execution": False,
        "radar_admission": "BLOCKED", "source_arbiter_admission": "BLOCKED",
        "live_trade": False, "can_confirm_signal": False,
        "operations": [
            {"name": "sdk_import", "operation": "COMPLETED"},
            {"name": "realtime_quote", "operation": "COMPLETED"}, *ops,
        ],
        "untrusted_payload": {"secret": "SECRET_DO_NOT_PRINT"},
    }
    dest = tmp_path / "private-sanitized.json"
    env = os.environ.copy()
    env.update({
        "STOCK_RAZOR_TICKFLOW_PROBE_CACHE_PATH": str(dest),
        "STOCK_RAZOR_PROBE_REPO_SHA": SHA,
        "TICKFLOW_ONE_QUOTE_SCOPE": "false",
    })
    p = subprocess.run(
        [sys.executable, "-c", script], input=json.dumps(fake),
        capture_output=True, text=True, timeout=5, check=False, env=env,
    )
    return p, dest


def _kline(name="kline_15m", **changes):
    evidence = {
        "sample_count": 3,
        "ohlcv_range_valid": True,
        "timestamp_monotonicity": "STRICTLY_INCREASING",
        "numeric_fields": {
            "open": True, "high": True, "low": True, "close": True,
            "volume": True, "amount": True,
        },
        "closure": "NOT_VERIFIED", "freshness": "NOT_VERIFIED",
        "raw_close": 99999999,
        "key": "SECRET_DO_NOT_PRINT",
    }
    evidence.update(changes)
    return {
        "name": name,
        "operation": "COMPLETED",
        "row_count": 3,
        "summary": evidence,
        "private_account_id": "SHOULD_NOT_BE_PUBLIC",
    }


@pytest.mark.parametrize("period", ["kline_15m", "kline_60m"])
def test_completed_kline_emits_only_finite_structure_not_close_or_timestamp(
    tmp_path, period,
):
    result, cache = _run_private_sanitizer(tmp_path, [_kline(period)])
    assert result.returncode == 0, result.stderr[:200]
    evidence = json.loads(result.stdout)
    item = evidence["operations"][2]
    assert item["name"] == period
    assert item["operation"] == "COMPLETED"
    assert item["bar_range_structure"] == "PASS"
    assert item["timestamp_order"] == "STRICTLY_INCREASING"
    assert item["numeric_ohlcv"] == "PASS"
    assert item["numeric_amount"] == "PASS"
    assert item["historical_sample_count"] == 3
    assert item["freshness"] == "NOT_VERIFIED"
    assert item["closure"] == "NOT_VERIFIED"
    assert evidence["data_qualification"] == "NOT_VERIFIED"
    assert evidence["radar_admission"] == "BLOCKED"
    assert evidence["source_arbiter_admission"] == "BLOCKED"
    assert evidence["live_trade"] is False
    assert json.loads(cache.read_text()) == evidence
    safe = json.dumps(evidence)
    assert "SECRET_DO_NOT_PRINT" not in safe
    assert "SHOULD_NOT_BE_PUBLIC" not in safe
    assert "99999999" not in safe
    assert "raw_close" not in safe
    assert "timestamp_first" not in safe and "timestamp_last" not in safe


@pytest.mark.parametrize("changes,expected", [
    ({"ohlcv_range_valid": False}, "FAIL"),
    ({"ohlcv_range_valid": "PASS"}, "NOT_VERIFIED"),
    ({"ohlcv_range_valid": True, "timestamp_monotonicity": "UNTRUSTED"}, "PASS"),
    ({"sample_count": True}, "PASS"),
    ({"numeric_fields": {"open": True, "high": True, "low": True,
                          "close": True, "volume": True, "amount": False}}, "PASS"),
])
def test_invalid_structure_fields_never_leak_unknown_values(tmp_path, changes, expected):
    result, _ = _run_private_sanitizer(tmp_path, [_kline(**changes)])
    assert result.returncode == 0, result.stderr[:200]
    item = json.loads(result.stdout)["operations"][2]
    assert item["bar_range_structure"] == expected
    assert item["timestamp_order"] in (
        "STRICTLY_INCREASING", "NON_DECREASING", "NOT_MONOTONIC",
        "NOT_VERIFIED",
    )
    assert item["historical_sample_count"] in (None, 3)
    if changes.get("ohlcv_range_valid") == "PASS":
        assert item["bar_range_structure"] == "NOT_VERIFIED"
    assert "UNTRUSTED" not in result.stdout
    assert "99999999" not in result.stdout
    assert json.loads(result.stdout)["live_trade"] is False


def test_public_workflow_reprojects_kline_schema_only_as_bounded_enums():
    wf = WORKFLOW.read_text(encoding="utf-8")
    assert 'if name in ("kline_15m","kline_60m"):' in wf
    assert 'record["bar_range_structure"]' in wf
    assert 'record["timestamp_order"]' in wf
    assert '("numeric_ohlcv","numeric_amount")' in wf
    assert "record[field]=val" in wf
    assert 'record["historical_sample_count"]' in wf
    assert 'record["provider_live_qualified"]=False' in wf
    assert '"data_qualification":"NOT_VERIFIED"' in wf
    assert '"radar_admission":"BLOCKED"' in wf
    assert "timestamp_first" not in wf
    assert "raw_close" not in wf
