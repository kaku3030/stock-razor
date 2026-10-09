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
