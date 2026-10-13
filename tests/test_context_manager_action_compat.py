"""Test pre-existing ChatGPT action schema can recover persisted context."""
import ast
from pathlib import Path
from unittest.mock import Mock

def _action(name, **deps):
    parsed = ast.parse(Path("realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8"))
    func = next(n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name == name)
    assert ast.unparse(func.decorator_list[0]) == "mcp.tool()"
    func.decorator_list = []
    ns = {"_CN_QUICK_SCAN_COMPAT_REQUEST": ["__QUICK_SCAN__"], **deps}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])),
                 "<readonly-action>", "exec"), ns)
    return ns[name]

def test_cn_existing_action_returns_exact_recovery_state():
    state = {"status": "ACTIVE", "safety": {"live_trade": False}}
    ctx, radar, quick = Mock(return_value=state), Mock(), Mock()
    fn = _action("get_cn_market_analysis", get_context_manager_state=ctx,
                 read_cn_radar_analysis=radar, read_cn_quick_scan=quick)
    assert fn(["__CONTEXT_MANAGER_STATE__"]) is state
    ctx.assert_called_once_with()
    radar.assert_not_called()
    quick.assert_not_called()

def test_us_existing_action_propagates_blocked_status_without_promotion():
    state = {"status": "BLOCKED", "reason": "STATE_UNAVAILABLE",
             "safety": {"radar_admission": "BLOCKED", "live_trade": False}}
    ctx, radar, cloud = Mock(return_value=state), Mock(), Mock()
    fn = _action("get_market_analysis", get_context_manager_state=ctx,
                 read_us_radar_analysis=radar, read_cloud_ops_status=cloud)
    assert fn(["__CONTEXT_MANAGER_STATE__"]) is state
    ctx.assert_called_once_with()
    radar.assert_not_called()
    cloud.assert_not_called()

def test_existing_market_and_compatibility_calls_stay_unchanged():
    ctx = Mock()
    cn, us = Mock(side_effect=lambda s: {"cn": s}), Mock(side_effect=lambda s: {"us": s})
    quick, cloud = Mock(return_value={"quick": True}), Mock(return_value={"cloud": True})
    cn_action = _action("get_cn_market_analysis", get_context_manager_state=ctx,
                        read_cn_radar_analysis=cn, read_cn_quick_scan=quick)
    us_action = _action("get_market_analysis", get_context_manager_state=ctx,
                        read_us_radar_analysis=us, read_cloud_ops_status=cloud)
    assert cn_action(["__QUICK_SCAN__"]) == {"quick": True}
    assert us_action(["__CLOUD_OPS_STATUS__"]) == {"cloud": True}
    for symbols in (None, [], ["159611"], ["AMD"],
                    ["__CONTEXT_MANAGER_STATE__", "AMD"],
                    ["__context_manager_state__"], ["__CONTEXT_MANAGER_STATE__ "]):
        assert cn_action(symbols) == {"cn": symbols}
        assert us_action(symbols) == {"us": symbols}
    ctx.assert_not_called()
