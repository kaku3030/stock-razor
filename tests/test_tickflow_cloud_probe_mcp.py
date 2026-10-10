"""TickFlow cloud probe MCP remains fail-closed and never calls provider SDK."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from data_provider.tickflow_cloud_probe_reader import read_tickflow_probe_health

NOW = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def sample(at=NOW):
    return {
        "schema": "stock_razor_tickflow_sanitized_probe_v0_1",
        "mode": "premium",
        "repo_sha": "a" * 40,
        "observed_at_utc": at.isoformat(),
        "operations": [
            {"name": "realtime_quote", "operation": "COMPLETED",
             "elapsed_ms": 488.0, "row_count": 2,
             "schema_qualified": False, "secret": "NEVER_LEAK"},
            {"name": "websocket_quote_smoke", "operation": "NO_EVENTS_OBSERVED"},
        ],
        "data_qualification": "NOT_VERIFIED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "api_key": "NEVER_LEAK",
    }


def test_missing_probe_cache_blocks(tmp_path):
    result = read_tickflow_probe_health(str(tmp_path / "none.json"), now_utc=NOW)
    assert result["ok"] is False and result["status"] == "UNAVAILABLE"
    assert result["data_admission"] == "BLOCKED"
    assert result["provider_requests"] == 0


def test_probe_is_observation_only_and_does_not_expose_unknown_fields(tmp_path):
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(sample()), encoding="utf-8")
    result = read_tickflow_probe_health(str(path), now_utc=NOW)
    assert result["ok"] is True and result["status"] == "PROBE_ONLY"
    assert result["production_tickflow_feed"] is False
    assert result["tickflow_to_radar_e2e"] == "NOT_VERIFIED"
    assert result["data_admission"] == "BLOCKED"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert result["operations"][0]["elapsed_ms"] == 488.0
    assert "NEVER_LEAK" not in json.dumps(result)


def test_stale_future_or_invalid_evidence_blocks(tmp_path):
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(sample(NOW - timedelta(hours=2))), encoding="utf-8")
    assert read_tickflow_probe_health(str(path), now_utc=NOW)["status"] == "STALE"
    path.write_text(json.dumps(sample(NOW + timedelta(minutes=2))), encoding="utf-8")
    assert read_tickflow_probe_health(str(path), now_utc=NOW)["status"] == "STALE"
    payload = sample()
    payload["operations"].append({"name": "malicious", "operation": "COMPLETED"})
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert read_tickflow_probe_health(str(path), now_utc=NOW)["status"] == "INVALID"


def test_reader_bounded_and_mcp_wired():
    server = (ROOT / "realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8")
    producer = (ROOT / "ops/aws/run_tickflow_premium_probe.sh").read_text(encoding="utf-8")
    assert "def get_tickflow_probe_health()" in server
    assert "return read_tickflow_probe_health()" in server
    assert "last-sanitized-probe.json" in producer
    assert "data_qualification" in producer
    assert "source_arbiter_admission" in producer
    assert "os.replace(tmp,dest)" in producer
    assert "os.chmod(tmp,0o644)" in producer


def test_provider_failure_and_ws_observed_are_valid_probe_evidence_only(tmp_path):
    payload = sample()
    payload["operations"] = [
        {"name": "kline_15m", "operation": "FAILED", "failure_class": "NetworkError"},
        {"name": "websocket_quote_smoke", "operation": "OBSERVED", "quote_events": 2},
    ]
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = read_tickflow_probe_health(str(path), now_utc=NOW)
    assert result["status"] == "PROBE_ONLY"
    assert [op["operation"] for op in result["operations"]] == ["FAILED", "OBSERVED"]
    assert result["data_admission"] == "BLOCKED"
    assert result["production_tickflow_feed"] is False
    assert "NetworkError" not in json.dumps(result)
    assert "quote_events" not in json.dumps(result)


def isolated_free_sample(at=NOW):
    return {
        "schema": "stock_razor_tickflow_isolated_probe_v0_1",
        "mode": "free",
        "location": "AWS_TOKYO_SSM_ISOLATE",
        "repo_sha": "b" * 40,
        "observed_at_utc": at.isoformat(),
        "operations": [
            {
                "name": "sdk_import",
                "operation": "COMPLETED",
            },
            {
                "name": "free_daily_kline",
                "operation": "COMPLETED",
                "row_count": 5,
                "summary": {
                    "sample_count": 5,
                    "timestamp_monotonicity": "STRICTLY_INCREASING",
                    "ohlcv_range_valid": True,
                    "closure": "NOT_VERIFIED",
                    "freshness": "NOT_VERIFIED",
                    "entitlement_evidence": "UNKNOWN",
                    "period": "1d",
                    "timestamp_first": 1,
                    "timestamp_last": 2,
                },
            },
        ],
        "historical_kline_observation": {
            "operation": "COMPLETED",
            "period": "1d",
            "row_count": 5,
            "qualification": "NOT_VERIFIED",
            "summary": {
                "sample_count": 5,
                "timestamp_monotonicity": "STRICTLY_INCREASING",
                "ohlcv_range_valid": True,
                "closure": "NOT_VERIFIED",
                "freshness": "NOT_VERIFIED",
                "entitlement_evidence": "UNKNOWN",
                "period": "1d",
                "timestamp_first": 1,
                "timestamp_last": 2,
            },
        },
    }


def test_isolated_free_probe_is_visible_but_not_admitted(tmp_path):
    path = tmp_path / "isolated.json"
    path.write_text(json.dumps(isolated_free_sample()), encoding="utf-8")
    result = read_tickflow_probe_health(str(path), now_utc=NOW)
    assert result["ok"] is True
    assert result["data_admission"] == "BLOCKED"
    assert result["radar_admission"] == "BLOCKED"
    assert result["historical_kline_observation"]["operation"] == "COMPLETED"
    assert result["historical_kline_observation"]["row_count"] == 5
    assert result["historical_kline_observation"]["summary"]["period"] == "1d"
    assert "timestamp_first" not in json.dumps(result)


def test_websocket_evidence_is_allowlisted_and_not_a_continuous_feed(tmp_path):
    payload = isolated_free_sample()
    payload["operations"].append({
        "name": "websocket_quote_smoke",
        "operation": "OBSERVED",
        "quote_callbacks": 3,
        "quote_events": 6,
        "unique_quote_samples": 4,
        "initial_snapshot_candidates": 2,
        "post_initial_update_candidates": 2,
        "duplicate_timestamp_events": 1,
        "out_of_order_timestamp_events": 0,
        "unrequested_symbol_events": 0,
        "invalid_timestamp_events": 0,
        "error_callbacks": 0,
        "connection_state": "UNKNOWN",
        "subscription_state": "UNKNOWN",
        "event_state": "PASS",
        "lag_scope": "POST_INITIAL_CANDIDATES_ONLY_NOT_VERIFIED_LIVE",
        "subscribed_ack_evidence": "NOT_OBSERVABLE_VIA_OFFICIAL_SYNC_SDK",
        "snapshot_vs_live_evidence": "NOT_VERIFIED",
        "ping_pong_evidence": "NOT_VERIFIED",
        "reconnect_resubscribe_evidence": "NOT_VERIFIED",
        "sample_latency_qualification": "NOT_VERIFIED",
        "clock_offset_qualification": "NOT_VERIFIED",
        "continuous_feed_qualified": False,
        "stale_drop_reconnect_qualified": False,
        "provider_secret": "NEVER_LEAK",
    })
    path = tmp_path / "isolated.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = read_tickflow_probe_health(str(path), now_utc=NOW)
    websocket = next(op for op in result["operations"] if op["name"] == "websocket_quote_smoke")
    assert websocket["quote_events"] == 6
    assert websocket["event_state"] == "PASS"
    assert websocket["continuous_feed_qualified"] is False
    assert websocket["reconnect_resubscribe_evidence"] == "NOT_VERIFIED"
    text = json.dumps(result)
    assert "provider_secret" not in text
    assert "NEVER_LEAK" not in text
