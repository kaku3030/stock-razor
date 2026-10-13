"""Offline regression for exact Cloud Ops alias in an already-registered MCP tool.

Extract the *actual* production function AST so these tests do not require
an MCP server, network listener, installed mcp SDK, AWS, or live providers.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path

import pytest

MCP_PATH = Path("realtime_monitor/readonly_mcp_server.py")


def _production_tool(cloud_reader, radar_reader):
    source = MCP_PATH.read_text(encoding="utf-8")
    module = ast.parse(source)
    original = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_market_analysis"
    )
    assert [ast.unparse(deco) for deco in original.decorator_list] == ["mcp.tool()"]
    function = deepcopy(original)
    function.decorator_list = []
    compiled = compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                       str(MCP_PATH), "exec")
    namespace = {
        "read_cloud_ops_status": cloud_reader,
        "read_us_radar_analysis": radar_reader,
    }
    exec(compiled, namespace)
    return namespace["get_market_analysis"]


def test_exact_singleton_existing_mcp_action_routes_to_cloud_ops_once():
    calls = []
    def cloud():
        calls.append(("cloud", None))
        return {
            "schema": "stock_razor_cloud_ops_readonly_v0_1",
            "status": "BLOCKED", "read_only": True,
            "mutation_allowed": False, "radar_admission": "BLOCKED",
            "source_arbiter_admission": "BLOCKED", "live_trade": False,
            "off_pc_independent_acquisition": "NOT_VERIFIED",
        }
    def radar(symbols):
        calls.append(("radar", symbols))
        return {"status": "RADAR_RESEARCH_STATE"}
    tool = _production_tool(cloud, radar)
    result = tool(["__CLOUD_OPS_STATUS__"])
    assert calls == [("cloud", None)]
    assert result["schema"] == "stock_razor_cloud_ops_readonly_v0_1"
    assert result["read_only"] and result["mutation_allowed"] is False
    assert result["status"] == result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert result["off_pc_independent_acquisition"] == "NOT_VERIFIED"


@pytest.mark.parametrize("args", [
    None,
    [],
    ["AMD"],
    ["US.AMD"],
    ["NVDA", "QQQ"],
    ["__CLOUD_OPS_STATUS__", "AMD"],
    ["AMD", "__CLOUD_OPS_STATUS__"],
    ["__cloud_ops_status__"],
    ["US.__CLOUD_OPS_STATUS__"],
    [" __CLOUD_OPS_STATUS__"],
    ["__CLOUD_OPS_STATUS__ "],
    "__CLOUD_OPS_STATUS__",
    ("__CLOUD_OPS_STATUS__",),
])
def test_every_other_request_remains_original_us_radar_contract(args):
    calls = []
    def cloud():
        pytest.fail("nonexact input must never invoke Cloud Ops")
    def radar(symbols):
        calls.append(symbols)
        return {"research_schema": "original_us_radar", "passed": symbols}
    result = _production_tool(cloud, radar)(args)
    assert calls == [args]
    assert result == {"research_schema": "original_us_radar", "passed": args}


def test_mcp_installer_smoke_covers_old_action_compatibility():
    installer = Path("ops/aws/install_readonly_mcp.sh").read_text(encoding="utf-8")
    server = MCP_PATH.read_text(encoding="utf-8")
    assert 'get_market_analysis(["__CLOUD_OPS_STATUS__"]),' in installer
    assert 'assert result["live_trade"] is False' in installer
    assert 'assert result["radar_admission"] == "BLOCKED"' in installer
    assert 'if symbols == ["__CLOUD_OPS_STATUS__"]:' in server
    assert "return read_cloud_ops_status()" in server
    assert "return read_us_radar_analysis(symbols)" in server
    assert "systemctl restart stock-razor-us-livefeed" not in installer
