"""Direct TickFlow WS-ACK AWS lane; all tests are synthetic and cost zero.

The raw quote frames, provider secret, AWS SSM and broker surfaces are never used.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.sanitize_tickflow_ws_protocol_probe import sanitize
from scripts.tickflow_ws_protocol_probe import ProtocolEvidence


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/probe-tickflow-aws-direct-ws-ack.yml"
BOOTSTRAP = ROOT / "ops/aws/run_tickflow_premium_probe.sh"
SHA = "c" * 40
SYMS = ("159611.SZ", "518880.SH")


def _sample(*, advances=2, errors=0, completed=True):
    e = ProtocolEvidence(SYMS)
    e.consume({"op": "subscribed", "channel": "quotes", "symbols": list(SYMS), "total": 2})
    for t in (1776754800000, *[1776754800000 + n * 1000 for n in range(1, advances + 1)]):
        e.consume({"op": "quotes", "data": [{
            "symbol": SYMS[0], "timestamp": t, "last_price": 99999999,
            "api_key": "DO_NOT_DISCLOSE_PROVIDER_CREDENTIAL",
        }]})
    for _ in range(errors):
        e.consume({"op": "error", "message": "AUTH=DO_NOT_LEAK"})
    e.window_status = "COMPLETED" if completed else "TERMINATED_EARLY"
    return e.summary(ws_handshake=True)


def test_valid_ack_full_window_and_two_advances_remain_not_live_qualified():
    raw = _sample()
    raw["api_key"] = "DO_NOT_DISCLOSE_PROVIDER_CREDENTIAL"
    raw["last_price"] = "NEVER_PRINT_THIS"
    out = sanitize(raw, repo_sha=SHA)
    assert out["protocol_acceptance"] == "PASS"
    assert out["subscription_ack"] == "PASS"
    assert out["bounded_window_status"] == "COMPLETED"
    assert out["counters"]["post_initial_update_candidates"] == 2
    assert out["protocol_progress_observation"] == "OBSERVED_NOT_QUALIFIED"
    assert out["continuous_feed_qualified"] is False
    assert out["data_qualification"] == "NOT_VERIFIED"
    assert out["source_arbiter_admission"] == "BLOCKED"
    assert out["radar_admission"] == "BLOCKED"
    assert out["live_trade"] is False
    assert out["trade_execution"] == "NO"
    rendered = json.dumps(out)
    assert "DO_NOT_DISCLOSE" not in rendered
    assert "last_price" not in rendered
    assert "99999999" not in rendered
    assert SYMS[0] not in rendered


@pytest.mark.parametrize("advances,errors,completed", [
    (0, 0, True), (1, 0, True), (2, 1, True), (2, 0, False),
])
def test_incomplete_ws_ack_window_or_progress_cannot_promote(
    advances, errors, completed,
):
    result = sanitize(_sample(advances=advances, errors=errors, completed=completed), repo_sha=SHA)
    assert result["protocol_progress_observation"] == "NOT_VERIFIED"
    assert result["data_qualification"] == "NOT_VERIFIED"
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert result["live_trade"] is False


@pytest.mark.parametrize("field,bad", [
    ("continuous_feed_qualified", True),
    ("radar_admission", "OPEN"),
    ("source_arbiter_admission", "PASS"),
    ("canonical_write", True),
    ("live_trade", True),
    ("order_execution", True),
    ("post_initial_update_not_proven_live", False),
    ("quote_frames", True),
    ("post_initial_update_candidates", -1),
])
def test_malicious_admission_or_invalid_counter_is_refused(field, bad):
    raw = _sample()
    if field in ("quote_frames", "post_initial_update_candidates"):
        raw[field] = bad
    else:
        raw[field] = bad
    with pytest.raises(ValueError):
        sanitize(raw, repo_sha=SHA)


def test_sanitizer_cli_is_fixed_allowlist_and_does_not_log_raw_failure():
    raw = _sample()
    raw["token"] = "SHOULD_NOT_REACH_PUBLIC_ACTIONS"
    p = subprocess.run(
        [sys.executable, str(ROOT / "scripts/sanitize_tickflow_ws_protocol_probe.py"),
         "--repo-sha", SHA],
        input=json.dumps(raw), text=True, capture_output=True,
        timeout=5, check=False,
    )
    assert p.returncode == 0, p.stderr
    safe = json.loads(p.stdout)
    assert safe["schema"] == "stock_razor_tickflow_ws_ack_sanitized_v0_1"
    assert "SHOULD_NOT_REACH_PUBLIC_ACTIONS" not in p.stdout

    bad = subprocess.run(
        [sys.executable, str(ROOT / "scripts/sanitize_tickflow_ws_protocol_probe.py"),
         "--repo-sha", SHA],
        input=json.dumps({"secret":"SHOULD_NOT_REACH_PUBLIC_ACTIONS"}),
        text=True, capture_output=True, timeout=5, check=False,
    )
    assert bad.returncode == 2
    assert "SHOULD_NOT_REACH_PUBLIC_ACTIONS" not in bad.stdout + bad.stderr
    assert json.loads(bad.stdout)["failure_class"] == "INVALID_EVIDENCE"


def test_manual_aws_workflow_has_exact_main_pins_secret_privacy_and_no_order_calls():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "default: false" in source
    assert "github.ref == 'refs/heads/main' && inputs.approve_paid_direct_ws_probe == true" in source
    assert "  push:" not in source and "  schedule:" not in source
    assert "persist-credentials: false" in source
    assert source.index("Guard protected main, paid scope and exact source before AWS OIDC") < source.index(
        "aws-actions/configure-aws-credentials@v4"
    )
    assert "git ls-remote origin refs/heads/main" in source
    assert "StockRazorGitHubOpsRole" in source
    assert "i-01738342af3efac72" in source
    assert "sha256sum scripts/tickflow_ws_protocol_probe.py" in source
    assert "sha256sum scripts/sanitize_tickflow_ws_protocol_probe.py" in source
    assert "AWS-RunShellScript" in source
    assert "RAW_SSM_OUTPUT_WITHHELD=YES" in source
    assert "TICKFLOW_WS_DATA_QUALIFICATION=PASS" not in source
    assert "TICKFLOW_WS_DATA_QUALIFICATION=NOT_VERIFIED" in source
    assert 'printf \'%s\' "$sanitized" | EXPECTED_REVISION="$GITHUB_SHA" python3 -c' in source
    assert 'echo "$private_output"' not in source
    for forbidden in ("systemctl restart", "systemctl stop", "unlock_trade",
                      "place_order", "cancel_order", "get-secret-value"):
        assert forbidden not in source


def test_existing_premium_seven_argument_mode_remains_and_protocol_only_avoids_rest():
    s = BOOTSTRAP.read_text(encoding="utf-8")
    assert 'if [[ "$#" -ne 7 && "$#" -ne 9 ]]' in s
    assert 'if [[ "$#" -eq 9 ]]' in s
    assert '[[ "$quote_only" == false && "$ws_seconds" != 0 ]]' in s
    assert "sha256sum -c - >/dev/null" in s
    assert "stage/ws_protocol.py" in s
    assert "stage/ws_sanitizer.py" in s
    assert 'ws_symbols="${TICKFLOW_WS_SYMBOLS:-159611.SZ 159209.SZ 512730.SH 159363.SZ}"' in s
    assert 'read -r -a ws_symbol_args <<< "$ws_symbols"' in s
    assert '--symbols "${ws_symbol_args[@]}" --seconds "$ws_seconds"' in s
    assert 'TICKFLOW_WS_PROTOCOL_PROBE_OPT_IN=true' in s
    assert 'TICKFLOW_PREMIUM_NETWORK_REQUEST_ENABLED=true' in s
    assert s.index('if [[ "$protocol_only" == true ]]; then\n  # Only one bounded') < s.index('probe_args=(--mode premium')
    assert 'exit 0\nfi\n\nprobe_stage=RUN_PREMIUM_PROBE' in s
    assert "unset TICKFLOW_API_KEY secret_json" in s
    assert "TICKFLOW_CLOUD_DATA_ADMISSION=BLOCKED" in s


@pytest.mark.parametrize("count,seconds,quote_only,protocol_hash", [
    (9, "0", "false", "a" * 64),
    (9, "30", "true", "a" * 64),
    (9, "30", "false", "INVALID_HASH"),
    (8, "30", "false", "a" * 64),
])
def test_invalid_ws_scope_hash_or_arg_count_vetoes_before_any_provider_io(
    count, seconds, quote_only, protocol_hash,
):
    args = [
        "a" * 40, "stock-razor/tickflow/premium-api-key",
        "b" * 64, "c" * 64, "d" * 64, seconds, quote_only,
        protocol_hash, "e" * 64,
    ][:count]
    import os
    env = os.environ.copy()
    env.update({
        "TICKFLOW_PREMIUM_PROBE_ENABLED": "false",
        "TICKFLOW_PREMIUM_NETWORK_REQUEST_ENABLED": "false",
        "TICKFLOW_API_KEY": "DONT_READ_OR_LOG",
    })
    p = subprocess.run(
        ["bash", str(BOOTSTRAP), *args],
        text=True, capture_output=True, timeout=5, check=False, env=env,
    )
    assert p.returncode != 0
    assert "DONT_READ_OR_LOG" not in p.stdout + p.stderr
    assert "TICKFLOW_PREMIUM_PROBE_EXECUTED=YES" not in p.stdout

def test_postinitial_event_lag_public_projection_is_finite_and_non_admitting():
    e = ProtocolEvidence(SYMS)
    e.consume({"op":"subscribed","channel":"quotes","symbols":list(SYMS),"total":2})
    stamp=1776754800000
    e.consume({"op":"quotes","data":[{"symbol":SYMS[0],"timestamp":stamp}]},received_at_ms=stamp+100000)
    e.consume({"op":"quotes","data":[{"symbol":SYMS[0],"timestamp":stamp+1000}]},received_at_ms=stamp+1700)
    e.consume({"op":"quotes","data":[{"symbol":SYMS[0],"timestamp":stamp+2000}]},received_at_ms=stamp+2800)
    e.window_status="COMPLETED"
    sanitized=sanitize(e.summary(ws_handshake=True),repo_sha=SHA)
    assert sanitized["post_initial_p95_lag_bucket"]=="UNDER_2S"
    assert sanitized["post_initial_lag_samples"]==2
    assert sanitized["timestamp_lag_qualification"]=="OBSERVED_NOT_QUALIFIED"
    assert sanitized["source_arbiter_admission"]=="BLOCKED"
    assert sanitized["data_qualification"]=="NOT_VERIFIED"

def test_false_fast_lag_claim_with_future_event_is_rejected():
    raw=_sample()
    raw["post_initial_p95_lag_bucket"]="UNDER_2S"
    raw["post_initial_future_timestamp_count"]=1
    with pytest.raises(ValueError):
        sanitize(raw,repo_sha=SHA)
