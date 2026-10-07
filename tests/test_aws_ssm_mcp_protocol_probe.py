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


def test_mcp_protocol_probe_requires_precomputed_market_analysis_tool():
    block = _probe_block()
    assert "get_market_analysis" in block
    assert "PRIVATE_MCP_TOOL_DISCOVERY_4_OF_4" in block
    assert "len(names)==4 and set(names)==allowed" in block


def test_secure_remote_e2e_calls_precomputed_market_analysis():
    start = WORKFLOW.index("            secure_mcp_remote_e2e)")
    end = WORKFLOW.index("            canonical_futures_mcp_remote_e2e)", start)
    block = WORKFLOW[start:end]
    assert "'get_market_analysis'" in block
    assert "Call get_market_analysis exactly once with valid read-only arguments." in block
    assert "len(names) != 4" in block
    assert "len(discovered) == 4" in block
