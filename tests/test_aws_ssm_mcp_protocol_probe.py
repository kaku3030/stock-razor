from pathlib import Path

WORKFLOW = Path(".github/workflows/aws-ssm-ops.yml").read_text(encoding="utf-8").replace("\\r\\n", "\\n")


def _probe_block() -> str:
    start = WORKFLOW.index("            mcp_protocol_probe)")
    end = WORKFLOW.index("            secure_mcp_remote_e2e)", start)
    return WORKFLOW[start:end]


def test_mcp_protocol_probe_uses_systemd_mainpid_not_ephemeral_literal():
    block = _probe_block()
    assert "unit='stock-razor-mcp.service'" in block
    assert 'systemctl show "$unit" -p MainPID --value' in block
    assert "MCP_PROBE_REASON=systemd-mainpid-not-evidenced" in block
    assert "pid=8607" not in block


def test_mcp_protocol_probe_binds_process_socket_and_source_to_same_mainpid():
    block = _probe_block()
    assert 'readlink -f /proc/$pid/cwd' in block
    assert "readonly_mcp_server.py" in block
    assert 'grep "pid=$pid,"' in block
    assert "127.0.0.1:8000" in block
    assert "MCP_PROBE_REASON=readonly-mcp-process-not-evidenced" in block


def test_mcp_protocol_probe_accepts_module_invocation_and_six_tool_surface():
    block = _probe_block()
    assert "grep -Eq 'readonly_mcp_server(\\.py|([[:space:]]|$))'" in block
    assert "has_streamable_run = any(" in block
    assert "kw.value.value == 'streamable-http'" in block
    assert "get_futures_runtime_health" in block
    assert "get_market_analysis" in block
    assert "get_cn_market_data" in block
    assert "PRIVATE_MCP_TOOL_DISCOVERY_6_OF_6" in block
    assert "len(names)==6 and set(names)==allowed" in block
    assert "call('get_market_analysis',{'symbols':['AMD']},'AMD')" in block
    assert "call('get_cn_market_data',{'symbol':'159611','timeframe':'1d','limit':1},'159611')" in block
