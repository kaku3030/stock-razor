"""Cloud Ops fallback over one pre-existing ChatGPT MCP action (offline)."""
import ast
from pathlib import Path
from unittest.mock import Mock

from data_provider.cloud_ops_readonly_status import _project


def _real_action(*, cloud_ops, quick_scan, radar):
    source = Path("realtime_monitor/readonly_mcp_server.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_cn_market_analysis"
    )
    assert len(fn.decorator_list) == 1
    assert ast.unparse(fn.decorator_list[0]) == "mcp.tool()"
    fn.decorator_list = []
    code = compile(
        ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
        "<cloud-ops-compat-action>", "exec",
    )
    scope = {
        "_CN_QUICK_SCAN_COMPAT_REQUEST": ["__QUICK_SCAN__"],
        "_CLOUD_OPS_COMPAT_REQUEST": ["__CLOUD_OPS__"],
        "read_cloud_ops_status": cloud_ops,
        "read_cn_quick_scan": quick_scan,
        "read_cn_radar_analysis": radar,
    }
    exec(code, scope)
    return scope["get_cn_market_analysis"]


def _cloud_response():
    return {
        "schema": "stock_razor_cloud_ops_readonly_v0_1",
        "status": "OPERATIONAL_OBSERVATION_ONLY",
        "ok": True,
        "read_only": True,
        "mutation_allowed": False,
        "aws_api_requests": 0,
        "provider_requests": 0,
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "paper_auto_ready": False,
        "live_trade": False,
        "can_confirm_signal": False,
        "off_pc_independent_acquisition": "NOT_VERIFIED",
        "data_currentness_proven": False,
    }


def test_exact_cloud_ops_sentinel_routes_to_existing_bounded_reader():
    expected = _cloud_response()
    cloud = Mock(return_value=expected)
    quick = Mock()
    radar = Mock()
    action = _real_action(cloud_ops=cloud, quick_scan=quick, radar=radar)
    assert action(["__CLOUD_OPS__"]) is expected
    cloud.assert_called_once_with()
    radar.assert_not_called()
    quick.assert_not_called()
    assert expected["mutation_allowed"] is False
    assert expected["radar_admission"] == "BLOCKED"
    assert expected["live_trade"] is False


def test_existing_cn_quick_scan_unchanged_and_no_cloud_calls():
    cloud = Mock()
    quick = Mock(return_value={"entry_gate": "ENTRY_BLOCKED", "live_trade": False})
    radar = Mock()
    action = _real_action(cloud_ops=cloud, quick_scan=quick, radar=radar)
    assert action(["__QUICK_SCAN__"]) == {
        "entry_gate": "ENTRY_BLOCKED", "live_trade": False,
    }
    quick.assert_called_once_with()
    cloud.assert_not_called()
    radar.assert_not_called()


def test_no_other_symbols_can_be_interpreted_as_cloud_maintenance():
    cloud = Mock()
    quick = Mock()
    radar = Mock(side_effect=lambda values: {"legacy": values})
    action = _real_action(cloud_ops=cloud, quick_scan=quick, radar=radar)
    inputs = [
        None, [], ["159611"], ["__CLOUD_OPS__", "159611"],
        ["__cloud_ops__"], ["__CLOUD_OPS__ "], ["__CLOUD_OPS__\n"],
        ["__CLOUD_OPS__", "__CLOUD_OPS__"], ["__QUICK_SCAN__", "159611"],
        ["__CLOUD_OPS__","__QUICK_SCAN__"], ["NOT_A_REAL_STOCK"],
    ]
    for values in inputs:
        assert action(values) == {"legacy": values}
    assert radar.call_count == len(inputs)
    cloud.assert_not_called()
    quick.assert_not_called()


def test_blocked_cloud_response_is_never_qualified_by_compat_route():
    blocked = dict(
        _cloud_response(),
        status="BLOCKED", ok=False, components={
            "us_radar": _project({
                "operational_state": "CLOCK_REVERSAL",
                "unit_active": True,
                "safety_evidence": "INCOMPLETE",
                "private_field": "SECRET_NEVER_OUTPUT",
            }),
        },
    )
    cloud = Mock(return_value=blocked)
    action = _real_action(cloud_ops=cloud, quick_scan=Mock(), radar=Mock())
    result = action(["__CLOUD_OPS__"])
    assert result is blocked
    assert result["ok"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert "SECRET_NEVER_OUTPUT" not in str(result)


def test_source_has_exact_sentinel_only_and_no_trading_mutation():
    mcp = Path("realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8")
    assert '_CLOUD_OPS_COMPAT_REQUEST = ["__CLOUD_OPS__"]' in mcp
    assert "return read_cloud_ops_status()" in mcp
    assert "return read_cn_radar_analysis(symbols)" in mcp
    assert "def get_cloud_ops_status() -> dict:" in mcp
    assert "systemctl restart" not in mcp
    assert "TRADE_EXECUTION=YES" not in mcp
