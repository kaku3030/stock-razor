"""Existing ChatGPT MCP action stays compatible when selecting TickFlow cache."""
from __future__ import annotations

import ast
from pathlib import Path


def _load_handler():
    source = Path("realtime_monitor/readonly_mcp_server.py").read_text("utf-8")
    tree = ast.parse(source)
    handler = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_cn_market_data"
    )
    handler.decorator_list = []
    calls = []

    def legacy(symbol, *, timeframe, limit):
        calls.append(("legacy", symbol, timeframe, limit))
        return {"source": "EASTMONEY_OR_TENCENT"}

    def tickflow(symbol, *, timeframe, limit, research_mode):
        calls.append(("tickflow", symbol, timeframe, limit, research_mode))
        if symbol not in ("159611.SZ", "518880.SH") or timeframe not in ("15m", "60m"):
            return {"ok": False, "status": "INVALID_REQUEST", "radar_admission": "BLOCKED"}
        return {"ok": True, "status": "PASS_HISTORICAL_ONLY", "radar_admission": "BLOCKED"}

    namespace = {
        "read_cn_market_data": legacy,
        "read_cn_tickflow_research_data": tickflow,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[handler], type_ignores=[])),
                 "<readonly_mcp_dispatch>", "exec"), namespace)
    return namespace["get_cn_market_data"], calls


def test_opt_in_only_tickflow_historical_cache():
    handler, calls = _load_handler()
    result = handler("TICKFLOW:159611.SZ", timeframe="15m", limit=1)
    assert result["status"] == "PASS_HISTORICAL_ONLY"
    assert calls == [("tickflow", "159611.SZ", "15m", 1, "historical_only")]


def test_normal_market_data_route_is_unchanged():
    handler, calls = _load_handler()
    assert handler("159611.SZ", timeframe="15m", limit=1)["source"] == "EASTMONEY_OR_TENCENT"
    assert handler("518880", timeframe="1d", limit=120)["source"] == "EASTMONEY_OR_TENCENT"
    assert calls == [
        ("legacy", "159611.SZ", "15m", 1),
        ("legacy", "518880", "1d", 120),
    ]


def test_malformed_prefixed_requests_do_not_fallback_to_legacy():
    handler, calls = _load_handler()
    assert handler("TICKFLOW:000001.SZ", timeframe="15m", limit=1)["status"] == "INVALID_REQUEST"
    assert handler("TICKFLOW:159611.SZ", timeframe="1d", limit=1)["status"] == "INVALID_REQUEST"
    assert all(item[0] == "tickflow" for item in calls)
