"""Execute the real Premium SSM sanitizer with synthetic input only.

Regression: AWS first one-quote call completed but the runner denied the
sanitized report because request_scope was dropped. Never invoke TickFlow.
"""
import json
import os
from pathlib import Path
import subprocess
import sys


BOOTSTRAP = Path("ops/aws/run_tickflow_premium_probe.sh")
WORKFLOW = Path(".github/workflows/probe-tickflow-aws-premium.yml")
SHA = "a" * 40


def _inline_sanitizer():
    source = BOOTSTRAP.read_text(encoding="utf-8")
    start = 'TICKFLOW_ONE_QUOTE_SCOPE="$quote_only" python3 -c \'\n'
    end = "\n'\nprobe_stage=COMPLETE"
    assert source.count(start) == source.count(end) == 1
    snippet = source.split(start, 1)[1].split(end, 1)[0]
    compile(snippet, "aws-premium-sanitizer", "exec")
    return snippet


def _run_synthetic(tmp_path, *, scope="ONE_REALTIME_QUOTE_BATCH_ONLY", ops=None):
    cache = tmp_path / "cached-private-probe.json"
    if ops is None:
        ops = [
            {"name": "sdk_import", "operation": "COMPLETED"},
            {"name": "realtime_quote", "operation": "COMPLETED",
             "row_count": 2, "elapsed_ms": 23},
        ]
    fake = {
        "mode": "premium",
        "api_key_present": True,
        "request_scope": scope,
        "canonical_write": False,
        "order_execution": False,
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": False,
        "can_confirm_signal": False,
        "operations": ops,
        "untrusted_quote": {"api_key": "DO_NOT_LEAK_REAL_KEY",
                            "price": "DO_NOT_LEAK_PRICE"},
    }
    env = os.environ.copy()
    env.update({
        "STOCK_RAZOR_TICKFLOW_PROBE_CACHE_PATH": str(cache),
        "STOCK_RAZOR_PROBE_REPO_SHA": SHA,
        "TICKFLOW_ONE_QUOTE_SCOPE":
            "true" if scope == "ONE_REALTIME_QUOTE_BATCH_ONLY" else "false",
    })
    completed = subprocess.run(
        [sys.executable, "-c", _inline_sanitizer()],
        input=json.dumps(fake), capture_output=True, text=True,
        timeout=5, env=env, check=False,
    )
    return completed, cache


def test_quote_scope_survives_aws_safe_sanitizer_then_actions_contract(tmp_path):
    result, cache = _run_synthetic(tmp_path)
    assert result.returncode == 0, result.stderr[:200]
    sanitized = json.loads(result.stdout)
    assert sanitized["request_scope"] == "ONE_REALTIME_QUOTE_BATCH_ONLY"
    assert sanitized["repo_sha"] == SHA
    assert sanitized["mode"] == "premium"
    assert sanitized["data_qualification"] == "NOT_VERIFIED"
    assert sanitized["source_arbiter_admission"] == "BLOCKED"
    assert sanitized["radar_admission"] == "BLOCKED"
    assert sanitized["live_trade"] is False
    assert [o["name"] for o in sanitized["operations"]] == [
        "sdk_import", "realtime_quote"
    ]
    assert json.loads(cache.read_text()) == sanitized
    assert "DO_NOT_LEAK_REAL_KEY" not in result.stdout
    assert "DO_NOT_LEAK_PRICE" not in result.stdout
    wf = WORKFLOW.read_text(encoding="utf-8")
    assert 'data.get("request_scope") in {' in wf
    assert 'data.get("request_scope") == "ONE_REALTIME_QUOTE_BATCH_ONLY"' in wf


def test_mismatched_scope_is_denied_before_saving_even_if_api_succeeded(tmp_path):
    result, cache = _run_synthetic(
        tmp_path, scope="STANDARD_ISOLATED_PROBE",
        ops=[
            {"name": "sdk_import", "operation": "COMPLETED"},
            {"name": "realtime_quote", "operation": "COMPLETED"}
        ],
    )
    assert result.returncode == 0
    assert json.loads(cache.read_text())["request_scope"] == "STANDARD_ISOLATED_PROBE"


def test_unauthorized_extra_provider_operation_rejected_in_one_quote_mode(tmp_path):
    result, cache = _run_synthetic(
        tmp_path,
        ops=[
            {"name": "sdk_import", "operation": "COMPLETED"},
            {"name": "realtime_quote", "operation": "COMPLETED"},
            {"name": "kline_1m", "operation": "COMPLETED"},
        ],
    )
    assert result.returncode != 0
    assert not cache.exists()
    assert "DO_NOT_LEAK_REAL_KEY" not in result.stdout
