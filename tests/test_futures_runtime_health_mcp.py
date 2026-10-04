import json
from datetime import datetime, timedelta, timezone

import realtime_monitor.server as server


def test_futures_runtime_health_missing_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "FUTURES_RUNTIME_STATUS_PATH", str(tmp_path / "missing.json"))
    result = server.get_futures_runtime_health()
    assert result["ok"] is False
    assert result["status"] == "UNAVAILABLE"
    assert result["realtime_verified"] is False
    assert result["live_trade"] is False


def test_futures_runtime_health_fresh_is_observation_only(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat.json"
    path.write_text(json.dumps({
        "type": "futures_runtime_heartbeat",
        "runtime_instance_id": "runtime-1", "generation": 1, "host_id": "host-1",
        "sequence": 7, "emitted_at_utc": datetime.now(timezone.utc).isoformat(),
        "attempted": ["GC", "CL", "SI", "HG"], "succeeded": ["GC", "CL", "SI", "HG"],
        "failed": [], "skipped_backoff": [], "cloud_runtime_verified": False,
        "pc_off_verified": False, "live_trade": False,
    }), encoding="utf-8")
    monkeypatch.setattr(server, "FUTURES_RUNTIME_STATUS_PATH", str(path))
    result = server.get_futures_runtime_health()
    assert result["ok"] is True
    assert result["status"] == "HEALTHY"
    assert result["realtime_verified"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_futures_runtime_health_future_timestamp_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat.json"
    path.write_text(json.dumps({
        "type": "futures_runtime_heartbeat",
        "runtime_instance_id": "runtime-1", "generation": 1, "host_id": "host-1",
        "sequence": 8, "emitted_at_utc": (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),
    }), encoding="utf-8")
    monkeypatch.setattr(server, "FUTURES_RUNTIME_STATUS_PATH", str(path))
    result = server.get_futures_runtime_health()
    assert result["ok"] is False
    assert result["status"] == "STALE"
    assert result["realtime_verified"] is False
    assert result["live_trade"] is False


def test_futures_runtime_health_naive_timestamp_is_invalid(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat.json"
    path.write_text(json.dumps({
        "type": "futures_runtime_heartbeat",
        "runtime_instance_id": "runtime-1", "generation": 1, "host_id": "host-1",
        "sequence": 9, "emitted_at_utc": "2026-10-04T12:00:00",
    }), encoding="utf-8")
    monkeypatch.setattr(server, "FUTURES_RUNTIME_STATUS_PATH", str(path))
    result = server.get_futures_runtime_health()
    assert result["ok"] is False
    assert result["status"] == "INVALID"
