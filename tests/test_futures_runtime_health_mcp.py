import json
from datetime import datetime, timedelta, timezone

from data_provider.futures_runtime_health import read_futures_runtime_health


NOW = datetime(2026, 10, 4, 14, 0, tzinfo=timezone.utc)


def heartbeat(emitted_at):
    return {
        "type": "futures_runtime_heartbeat",
        "runtime_instance_id": "runtime-1", "generation": 1, "host_id": "host-1",
        "sequence": 7, "emitted_at_utc": emitted_at,
        "attempted": ["GC", "CL", "SI", "HG"], "succeeded": ["GC", "CL", "SI", "HG"],
        "failed": [], "skipped_backoff": [], "cloud_runtime_verified": False,
        "pc_off_verified": False, "live_trade": False,
    }


def test_missing_file_fails_closed(tmp_path):
    result = read_futures_runtime_health(str(tmp_path / "missing.json"), now_utc=NOW)
    assert result["ok"] is False
    assert result["status"] == "UNAVAILABLE"
    assert result["realtime_verified"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_fresh_heartbeat_is_observation_only(tmp_path):
    path = tmp_path / "heartbeat.json"
    path.write_text(json.dumps(heartbeat((NOW - timedelta(seconds=60)).isoformat())), encoding="utf-8")
    result = read_futures_runtime_health(str(path), now_utc=NOW)
    assert result["ok"] is True
    assert result["status"] == "HEALTHY"
    assert result["realtime_verified"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_future_timestamp_fails_closed(tmp_path):
    path = tmp_path / "heartbeat.json"
    path.write_text(json.dumps(heartbeat((NOW + timedelta(minutes=5)).isoformat())), encoding="utf-8")
    result = read_futures_runtime_health(str(path), now_utc=NOW)
    assert result["ok"] is False
    assert result["status"] == "STALE"
    assert result["realtime_verified"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_naive_timestamp_is_invalid(tmp_path):
    path = tmp_path / "heartbeat.json"
    path.write_text(json.dumps(heartbeat("2026-10-04T14:00:00")), encoding="utf-8")
    result = read_futures_runtime_health(str(path), now_utc=NOW)
    assert result["ok"] is False
    assert result["status"] == "INVALID"
    assert result["radar_admission"] == "BLOCKED"


def test_stale_timestamp_does_not_promote_permissions(tmp_path):
    path = tmp_path / "heartbeat.json"
    path.write_text(json.dumps(heartbeat((NOW - timedelta(minutes=10)).isoformat())), encoding="utf-8")
    result = read_futures_runtime_health(str(path), now_utc=NOW)
    assert result["ok"] is False
    assert result["status"] == "STALE"
    assert result["realtime_verified"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
