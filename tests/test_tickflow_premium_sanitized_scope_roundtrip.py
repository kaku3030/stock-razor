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



def _contains_exact_quote_price_leaf(value):
    """Reject literal price values, not coincidental digits in ISO timestamps.

    E.g. an observed_at_utc timestamp may contain '1.11' as ordinary digits.
    Check only complete primitive leaf values, and separately deny raw keys.
    """
    if isinstance(value, dict):
        return any(_contains_exact_quote_price_leaf(x) for x in value.values())
    if isinstance(value, list):
        return any(_contains_exact_quote_price_leaf(x) for x in value)
    return type(value) in (int, float, str) and value in (1.11, 2.22, "1.11", "2.22")


def test_quote_price_leaf_guard_ignores_iso_timestamp_substrings():
    safe = {"observed_at_utc": "2026-10-13T06:43:01.117797+00:00"}
    assert "1.11" in json.dumps(safe)
    assert _contains_exact_quote_price_leaf(safe) is False
    assert _contains_exact_quote_price_leaf({"quote_prices": [1.11, 2.22]}) is True
    assert _contains_exact_quote_price_leaf({"raw": "1.11"}) is True

def test_websocket_counters_survive_private_sanitizer_without_quote_or_secret(tmp_path):
    ws={
        "name":"websocket_quote_smoke",
        "operation":"OBSERVED",
        "quote_callbacks":5,"quote_events":9,"unique_quote_samples":4,
        "initial_snapshot_candidates":2,
        "post_initial_update_candidates":2,
        "duplicate_timestamp_events":3,
        "out_of_order_timestamp_events":0,
        "unrequested_symbol_events":0,
        "invalid_timestamp_events":0,
        "error_callbacks":0,
        "connection_call":"PASS",
        "subscription_call":"PASS",
        "arrival_minus_provider_timestamp_ms":{"p95":112.4},
        "secret":"UNSAFE_ACCOUNT_PRIVATE_STRING",
        "quote_prices":[1.11,2.22],
    }
    completed, cache=_run_synthetic(
        tmp_path,scope="STANDARD_ISOLATED_PROBE",
        ops=[
            {"name":"sdk_import","operation":"COMPLETED"},
            {"name":"realtime_quote","operation":"COMPLETED","row_count":2},
            ws,
        ],
    )
    assert completed.returncode == 0, completed.stderr[:150]
    data=json.loads(completed.stdout)
    sanitized=data["operations"][2]
    assert sanitized["name"]=="websocket_quote_smoke"
    assert sanitized["quote_events"]==9
    assert sanitized["quote_callbacks"]==5
    assert sanitized["post_initial_update_candidates"]==2
    assert sanitized["initial_snapshot_candidates"]==2
    assert sanitized["connection_call"]=="PASS"
    assert sanitized["subscription_call"]=="PASS"
    assert sanitized["subscription_ack_evidence"]=="NOT_OBSERVABLE_VIA_OFFICIAL_SYNC_SDK"
    assert sanitized["sample_latency_qualification"]=="NOT_VERIFIED"
    assert sanitized["post_initial_candidates_not_confirmed_live"] is True
    assert "arrival_minus_provider_timestamp_ms" not in sanitized
    result_json=json.dumps(data)
    assert "UNSAFE_ACCOUNT_PRIVATE_STRING" not in result_json
    assert '"quote_prices"' not in result_json
    assert not _contains_exact_quote_price_leaf(data)
    assert json.loads(cache.read_text())==data
    assert data["radar_admission"]=="BLOCKED"
    assert data["source_arbiter_admission"]=="BLOCKED"


def test_websocket_bad_counters_cannot_escape_summary(tmp_path):
    ws={
        "name":"websocket_quote_smoke", "operation":"NO_EVENTS_OBSERVED",
        "quote_events":True, "quote_callbacks":-4,
        "post_initial_update_candidates":999999999,
        "error_callbacks":0,
        "connection_call":"PASS",
        "subscription_call":"MALICIOUS_STRING",
    }
    result, _=_run_synthetic(
        tmp_path,scope="STANDARD_ISOLATED_PROBE",
        ops=[{"name":"sdk_import","operation":"COMPLETED"},ws],
    )
    assert result.returncode==0
    safe=json.loads(result.stdout)["operations"][1]
    assert "quote_events" not in safe
    assert "quote_callbacks" not in safe
    assert "post_initial_update_candidates" not in safe
    assert safe["error_callbacks"]==0
    assert "subscription_call" not in safe
    assert safe["sample_latency_qualification"]=="NOT_VERIFIED"


def test_actions_redacts_raw_stream_details_but_retains_safe_counts():
    wf=WORKFLOW.read_text(encoding="utf-8")
    producer=BOOTSTRAP.read_text(encoding="utf-8")
    assert 'item["post_initial_candidates_not_confirmed_live"]=True' in producer
    assert 'record["provider_live_qualified"]=False' in wf
    assert 'assert item.get("sample_latency_qualification") == "NOT_VERIFIED"' in wf
    assert 'record[field]=val' in wf
    assert "echo \"$output\"" not in wf
    assert "arrival_minus_provider_timestamp_ms" not in producer
