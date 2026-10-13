"""Unit-test the actual MCP action function without requiring optional MCP SDK in CI."""
import ast
from pathlib import Path
from unittest.mock import Mock


def _action(*, radar, quick):
    source = Path("realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8")
    parsed = ast.parse(source)
    fn = next(
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_cn_market_analysis"
    )
    assert len(fn.decorator_list) == 1
    assert ast.unparse(fn.decorator_list[0]) == "mcp.tool()"
    # Only compile the real function, dropping its MCP registration decorator.
    # The full server import is tested by canonical AWS installer smoke.
    fn.decorator_list = []
    code = compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                   "<canonical-mcp-action>", "exec")
    namespace = {
        "_CN_QUICK_SCAN_COMPAT_REQUEST": ["__QUICK_SCAN__"],
        "read_cn_radar_analysis": radar,
        "read_cn_quick_scan": quick,
    }
    exec(code, namespace)
    return namespace["get_cn_market_analysis"]


def test_exact_sentinel_uses_existing_readonly_quick_scan():
    compact = {"status": "RESEARCH_ONLY", "entry_gate": "ENTRY_BLOCKED",
               "live_trade": False, "provider_requests": 0}
    quick = Mock(return_value=compact)
    radar = Mock()
    action = _action(radar=radar, quick=quick)
    assert action(["__QUICK_SCAN__"]) is compact
    quick.assert_called_once_with()
    radar.assert_not_called()


def test_default_and_normal_arguments_preserve_legacy_response():
    radar = Mock(side_effect=lambda symbols: {"legacy_input": symbols})
    quick = Mock()
    action = _action(radar=radar, quick=quick)
    for symbols in (None, [], ["159611"], ["159611", "512730"],
                    ["__QUICK_SCAN__", "159611"], ["__quick_scan__"],
                    ["__QUICK_SCAN__ "], ["invalid_symbol"]):
        assert action(symbols) == {"legacy_input": symbols}
    assert radar.call_count == 8
    quick.assert_not_called()


def test_blocked_compact_result_is_returned_unchanged():
    blocked = {"status": "BLOCKED", "reasons": ["SOURCE_IDENTITY_MISMATCH"],
               "entry_gate": "ENTRY_BLOCKED", "can_confirm_signal": False,
               "radar_admission": "BLOCKED", "live_trade": False}
    action = _action(radar=Mock(), quick=Mock(return_value=blocked))
    assert action(["__QUICK_SCAN__"]) is blocked
    assert blocked["entry_gate"] == "ENTRY_BLOCKED"
