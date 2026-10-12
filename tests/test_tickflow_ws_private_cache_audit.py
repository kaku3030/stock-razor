"""Execute the actual private AWS cache-audit code with synthetic files only.

Never invoke AWS, TickFlow SDK, network, provider, or accounts.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

WORKFLOW=Path(".github/workflows/audit-existing-tickflow-quote-cache.yml")
SHA="d"*40


def _run_cached_audit(tmp_path, *, ws=None, expected=SHA):
    script=WORKFLOW.read_text(encoding="utf-8")
    start="          python3 - <<'PY'\n"
    end="\n          PY\n"
    assert script.count(start)==script.count(end)==1
    embedded=textwrap.dedent(script.split(start,1)[1].split(end,1)[0])
    path=tmp_path/"sanitized-previous-probe.json"
    embedded=embedded.replace(
        'Path("/opt/stock-razor-tickflow-premium-probe/last-sanitized-probe.json")',
        f"Path({str(path)!r})"
    )
    compile(embedded, "<private-SSM-tickflow-cache-audit>", "exec")
    sample={
        "schema":"stock_razor_tickflow_sanitized_probe_v0_1",
        "repo_sha":SHA,"request_scope":"STANDARD_ISOLATED_PROBE",
        "data_qualification":"NOT_VERIFIED","radar_admission":"BLOCKED",
        "source_arbiter_admission":"BLOCKED","live_trade":False,
        "operations":[
            {"name":"sdk_import","operation":"COMPLETED"},
            {"name":"realtime_quote","operation":"COMPLETED","row_count":2},
        ],
        "raw_broker_account_id":"PRIVATE_SHOULD_NOT_LEAK",
    }
    if ws is not None:
        sample["operations"].append(ws)
    path.write_text(json.dumps(sample),encoding="utf-8")
    env=os.environ.copy()
    env["TICKFLOW_EXPECTED_PROBE_SHA"]=expected
    result=subprocess.run(
        [sys.executable,"-c",embedded],text=True,
        capture_output=True,check=False,timeout=4,env=env
    )
    assert result.returncode==0, result.stderr[:150]
    assert result.stdout.count("TICKFLOW_CACHE_SANITIZED=")==1
    return json.loads(result.stdout.strip().split("=",1)[1]), result.stdout


def ws(operation="OBSERVED",**updates):
    fields={
        "name":"websocket_quote_smoke","operation":operation,
        "quote_callbacks":4,"quote_events":7,
        "initial_snapshot_candidates":2,
        "post_initial_update_candidates":3,
        "connection_call":"PASS","subscription_call":"PASS",
        "subscription_ack_evidence":"NOT_OBSERVABLE_VIA_OFFICIAL_SYNC_SDK",
        "sample_latency_qualification":"NOT_VERIFIED",
        "provider_live_qualified":False,
        "payload":"PRIVATE_TICK_PRICE_MARKER"
    }
    fields.update(updates)
    return fields


def test_private_cache_audit_retains_bounded_ws_evidence_never_prices(tmp_path):
    result,output=_run_cached_audit(tmp_path,ws=ws())
    assert result["status"]=="REVIEW_ONLY"
    assert result["quote_rows"]==2
    assert result["ws_operation"]=="OBSERVED"
    assert result["ws_quote_callbacks"]==4
    assert result["ws_quote_events"]==7
    assert result["ws_initial_snapshot_candidates"]==2
    assert result["ws_post_initial_update_candidates"]==3
    assert result["ws_connection_call"]=="PASS"
    assert result["ws_subscription_call"]=="PASS"
    assert result["ws_provider_live_qualified"] is False
    assert result["provider_requests"]==0
    assert result["data_admission"]==result["radar_admission"]=="BLOCKED"
    assert "PRIVATE_SHOULD_NOT_LEAK" not in output
    assert "PRIVATE_TICK_PRICE_MARKER" not in output


def test_no_event_closed_session_is_observation_not_stream_quality(tmp_path):
    item=ws("NO_EVENTS_OBSERVED",quote_callbacks=0,quote_events=0,
            post_initial_update_candidates=0,initial_snapshot_candidates=0)
    result,_=_run_cached_audit(tmp_path,ws=item)
    assert result["status"]=="REVIEW_ONLY"
    assert result["ws_quote_events"]==0
    assert result["ws_operation"]=="NO_EVENTS_OBSERVED"
    assert result["ws_provider_live_qualified"] is False


def test_wrong_pinned_sha_cannot_report_any_ws_evidence_as_current(tmp_path):
    result,_=_run_cached_audit(tmp_path,ws=ws(),expected="e"*40)
    assert result["revision_matches"] is False
    assert result["status"]=="NOT_VERIFIED"
    assert result["ws_operation"]=="UNKNOWN"
    assert result["ws_quote_events"]==0
    assert result["ws_connection_call"]=="UNKNOWN"


def test_malicious_ws_ack_and_latency_claim_fail_closed(tmp_path):
    bad=ws(
        subscription_ack_evidence="PROVIDER_SUBSCRIBED_AND_LIVE",
        sample_latency_qualification="PROVEN",
    )
    result,output=_run_cached_audit(tmp_path,ws=bad)
    assert result["status"]=="NOT_VERIFIED"
    assert result["reason"]=="CACHE_MALFORMED_OR_UNAVAILABLE"
    assert result["radar_admission"]=="BLOCKED"
    assert result["ws_provider_live_qualified"] is False
    assert "PRIVATE_TICK_PRICE_MARKER" not in output


def test_ill_typed_or_extreme_counters_drop_to_zero(tmp_path):
    result,_=_run_cached_audit(
        tmp_path,ws=ws(quote_events=True,quote_callbacks=-1,
                       post_initial_update_candidates=10**15)
    )
    assert result["ws_quote_events"]==0
    assert result["ws_quote_callbacks"]==0
    assert result["ws_post_initial_update_candidates"]==0
    assert result["ws_provider_live_qualified"] is False


def test_workflow_audit_is_read_only_for_all_provider_interfaces():
    wf=WORKFLOW.read_text(encoding="utf-8")
    assert "TICKFLOW_CACHE_AUDIT_SANITIZED=" in wf
    assert '"ws_provider_live_qualified":False' in wf
    for unsafe in ("quotes.get(","klines.get(","stream.subscribe(","import tickflow",
                   "get-secret-value","aws s3 cp"):
        assert unsafe not in wf
