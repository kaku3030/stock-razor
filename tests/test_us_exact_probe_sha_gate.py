"""Executable regression for exact-SHA US cloud probe runner admission.

Runs only the already-embedded GitHub Actions sanitizing Python snippet with
synthetic JSON. Never invokes AWS, SSM, OpenD, or a broker.
"""
import json
from pathlib import Path
import subprocess
import sys
import textwrap


def _runner_inline_python() -> str:
    workflow = Path(".github/workflows/probe-us-cloud-exact.yml").read_text(
        encoding="utf-8"
    )
    start = """printf '%s' "$report" | python3 -c '\n"""
    assert workflow.count(start) == 1
    body = workflow.split(start, 1)[1].split("\n          '\n", 1)[0]
    code = textwrap.dedent(body)
    compile(code, "<github-actions-inline-python>", "exec")
    return code


def _synthetic_report(sha_status: str) -> str:
    return json.dumps({
        "schema": "stock_razor_us_exact_cloud_probe_v1",
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": "NO",
        "runtime_exact_sha": sha_status,
        "continuous_live_quote_sequence": {"status": "NOT_VERIFIED"},
        "timestamp_freshness": {"status": "NOT_VERIFIED"},
        "bar_closure_15m_60m": {"status": "NOT_VERIFIED"},
    })


def _run_report(value: str):
    return subprocess.run(
        [sys.executable, "-c", _runner_inline_python()],
        input=value,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )


def test_correct_source_sha_allows_readonly_probe_transport_success():
    outcome = _run_report(_synthetic_report("PASS"))
    assert outcome.returncode == 0
    assert "US_EXACT_CLOUD_PROBE_SANITIZED=" in outcome.stdout
    assert '"runtime_exact_sha": "PASS"' in outcome.stdout
    assert "US_EXACT_CLOUD_RUNTIME_SHA=NOT_VERIFIED" not in outcome.stderr


def test_wrong_or_missing_runtime_sha_cannot_be_reported_as_success():
    for sha_state in ("NOT_VERIFIED", "UNKNOWN", "BLOCKED", ""):
        outcome = _run_report(_synthetic_report(sha_state))
        assert outcome.returncode == 3
        assert "US_EXACT_CLOUD_PROBE_SANITIZED=" in outcome.stdout
        assert "US_EXACT_CLOUD_RUNTIME_SHA=NOT_VERIFIED" in outcome.stderr
        assert "AccountID" not in outcome.stdout


def test_invalid_safety_envelope_does_not_generate_a_success():
    sample = json.loads(_synthetic_report("PASS"))
    sample["radar_admission"] = "ENABLED"
    outcome = _run_report(json.dumps(sample))
    assert outcome.returncode != 0
    assert "US_EXACT_CLOUD_PROBE_SANITIZED=" not in outcome.stdout


def test_truncated_ssm_json_is_never_accepted():
    outcome = _run_report(_synthetic_report("PASS")[:-12])
    assert outcome.returncode != 0
    assert "US_EXACT_CLOUD_PROBE_SANITIZED=" not in outcome.stdout
