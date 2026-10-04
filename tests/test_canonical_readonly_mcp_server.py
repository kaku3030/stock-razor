from pathlib import Path


def test_canonical_readonly_mcp_declares_futures_health_tool():
    source = Path("realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8")
    assert 'FastMCP("stock-razor-readonly")' in source
    assert "@mcp.tool()" in source
    assert "def get_futures_runtime_health()" in source
    assert "return read_futures_runtime_health()" in source


def test_installer_keeps_runtime_read_only_and_exact_sha():
    source = Path("ops/aws/install_readonly_mcp.sh").read_text(encoding="utf-8")
    assert 'REPO_REF="${REPO_REF:?REPO_REF exact commit SHA is required}"' in source
    assert "read_futures_runtime_health" in source
    assert 'assert result["live_trade"] is False' in source
    assert 'assert result["radar_admission"] == "BLOCKED"' in source
