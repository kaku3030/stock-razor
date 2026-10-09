"""Static safety contract for TickFlow AWS SSM MCP cache audit."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = (ROOT / ".github/workflows/aws-ssm-ops.yml").read_text(encoding="utf-8")


def _audit():
    start = OPS.index("            tickflow_mcp_cache_audit)\n")
    end = OPS.index("            us_opend_subscription_audit)\n", start)
    return OPS[start:end]


def test_tickflow_mcp_audit_is_explicitly_read_only():
    script = _audit()
    assert "          - tickflow_mcp_cache_audit\n" in OPS
    assert "read_tickflow_probe_health()" in script
    assert "stock-razor-mcp.service" in script
    assert "DATA_ADMISSION=BLOCKED" in script
    assert "SOURCE_ARBITER_ADMISSION=BLOCKED" in script
    assert "LIVE_TRADE=NO" in script
    assert "SUBSCRIPTION_CHANGES=NONE" in script
    assert "systemctl restart" not in script
    assert "aws secretsmanager" not in script
    assert "subscribe(" not in script
    assert "TickFlow(" not in script
    assert "get_market_bars" not in script
    assert "print(p.stdout)" not in script
    assert "print(p.stderr)" not in script


def test_audit_never_promotes_production_status():
    script = _audit()
    assert '"production_tickflow_feed":False' in script
    assert '"data_admission":"BLOCKED"' in script
    assert '"radar_admission":"BLOCKED"' in script
    assert '"live_trade":False' in script
    assert 'len(p.stdout)<2048' in script
    assert '"PROBE_ONLY","STALE","INVALID","UNAVAILABLE"' in script
