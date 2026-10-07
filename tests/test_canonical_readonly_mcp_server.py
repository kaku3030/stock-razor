from pathlib import Path


def test_canonical_readonly_mcp_declares_futures_health_tool():
    source = Path("realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8")
    assert 'FastMCP("stock-razor-readonly")' in source
    assert "@mcp.tool()" in source
    assert "def get_futures_runtime_health()" in source
    assert "return read_futures_runtime_health()" in source


def test_canonical_readonly_mcp_declares_us_fast_read_tools():
    source = Path("realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8")
    for name in ("get_livefeed_health", "get_market_snapshots", "get_market_bars", "get_market_analysis"):
        assert f"def {name}(" in source
    assert "read_us_livefeed_health()" in source
    assert "read_us_market_snapshots(symbols)" in source
    assert "read_us_market_bars(symbol, timeframe=timeframe, limit=limit)" in source
    assert "read_us_radar_analysis(symbols)" in source



def test_canonical_readonly_mcp_declares_cn_fast_read_tool():
    source = Path("realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8")
    assert "def get_cn_market_data(" in source
    assert "read_cn_market_data(symbol, timeframe=timeframe, limit=limit)" in source


def test_installer_keeps_runtime_read_only_and_exact_sha():
    source = Path("ops/aws/install_readonly_mcp.sh").read_text(encoding="utf-8")
    assert 'REPO_REF="${REPO_REF:?REPO_REF exact commit SHA is required}"' in source
    assert "get_futures_runtime_health" in source
    assert "get_cn_market_data" in source
    assert "get_livefeed_health" in source
    assert "get_market_snapshots" in source
    assert "get_market_bars" in source
    assert "get_market_analysis" in source
    assert "STOCK_RAZOR_US_LIVEFEED_STATUS_PATH" in source
    assert "STOCK_RAZOR_US_CANONICAL_SNAPSHOT_PATH" in source
    assert "STOCK_RAZOR_US_RADAR_STATUS_PATH" in source
    assert "STOCK_RAZOR_CN_EASTMONEY_STATUS_PATH" in source
    assert 'assert result["live_trade"] is False' in source
    assert 'assert result["radar_admission"] == "BLOCKED"' in source
