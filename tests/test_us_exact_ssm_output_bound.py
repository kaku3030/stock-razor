"""Prevent 24KB SSM StandardOutput truncation and public heartbeat leaks."""
import json
from pathlib import Path
import sys

import pytest

from scripts import probe_us_cloud_exact as module


def sample():
    return {
        "schema": "stock_razor_us_exact_cloud_probe_v1",
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": "NO",
        "runtime_exact_sha": "NOT_VERIFIED",
        "continuous_live_quote_sequence": {"status": "NOT_VERIFIED"},
        "timestamp_freshness": {"status": "NOT_VERIFIED"},
        "bar_closure_15m_60m": {"status": "NOT_VERIFIED"},
        "latest_heartbeat": {"private": "H" * 120_000},
        "latest_radar": {"private": "R" * 120_000},
        "samples": [{"full": "S" * 120_000}],
    }


def test_ssm_stdout_summary_is_bounded_and_redacted(monkeypatch, capsys):
    monkeypatch.setattr(module, "probe", lambda **kwargs: sample())
    monkeypatch.setattr(sys, "argv", [
        "probe.py", "--expected-sha", "a" * 40,
        "--duration-seconds", "30", "--ssm-summary-only",
    ])
    assert module.main() == 0
    raw = capsys.readouterr().out
    assert len(raw.encode("utf-8")) < 2048
    result = json.loads(raw)
    assert result["schema"] == "stock_razor_us_exact_cloud_probe_v1"
    assert result["runtime_exact_sha"] == "NOT_VERIFIED"
    assert "H" * 30 not in raw
    assert "latest_heartbeat" not in raw
    assert "latest_radar" not in raw
    assert "samples" not in raw
    assert result["radar_admission"] == "BLOCKED"
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert result["live_trade"] == "NO"


def test_no_summary_when_any_safety_gate_invalid():
    for key, value in (
        ("schema", "invalid"),
        ("radar_admission", "PASS"),
        ("source_arbiter_admission", "PASS"),
        ("live_trade", "YES"),
    ):
        obj = sample()
        obj[key] = value
        with pytest.raises(ValueError):
            module.sanitized_ssm_summary(obj)


def test_workflow_uses_summary_before_ssm_log_capture():
    wf = Path(".github/workflows/probe-us-cloud-exact.yml").read_text(
        encoding="utf-8"
    )
    assert "--ssm-summary-only" in wf
    assert "StandardErrorContent" not in wf
    assert "print(json.dumps(x, sort_keys=True))" not in wf
    assert "systemctl restart" not in wf
