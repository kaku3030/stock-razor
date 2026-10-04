from pathlib import Path

from realtime_monitor import readonly_mcp_server


def test_canonical_readonly_mcp_registers_futures_health_tool():
    assert readonly_mcp_server.mcp is not None
    source = Path("realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8")
    assert "get_futures_runtime_health" in source


def test_canonical_tool_delegates_fail_closed(tmp_path, monkeypatch):
    missing = tmp_path / "missing.json"
    monkeypatch.setenv("STOCK_RAZOR_FUTURES_STATUS_PATH", str(missing))
    result = readonly_mcp_server.get_futures_runtime_health()
    assert result["ok"] is False
    assert result["realtime_verified"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
