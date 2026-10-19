"""Contract tests for the frozen ChatGPT MCP TickFlow batch route."""
from __future__ import annotations

import ast
from pathlib import Path


def make_readers(*, missing=None, different_sequence=None):
    src = Path("realtime_monitor/readonly_mcp_server.py").read_text("utf-8")
    tree = ast.parse(src)
    nodes = []
    for name in ("_read_tickflow_historical_batch", "get_cn_market_data"):
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == name)
        node.decorator_list = []
        nodes.append(node)
    calls = []

    def fake_tickflow(symbol, *, timeframe, limit, research_mode):
        calls.append((symbol, timeframe, limit, research_mode))
        assert research_mode == "historical_only"
        state = "STALE" if (symbol, timeframe) == missing else "PASS_HISTORICAL_ONLY"
        return {
            "ok": state == "PASS_HISTORICAL_ONLY",
            "status": state, "research_only": True,
            "radar_admission": "BLOCKED",
            "source_arbiter_admission": "BLOCKED",
            "bar_finality": "NOT_VERIFIED", "live_trade": False,
            "provider_requests": 0,
            "repo_sha": "a" * 40,
            "sequence": 9 + int((symbol, timeframe) == different_sequence),
            "source_age_seconds": 15.0,
            "expected_grid_progress": "DUE_LABEL_NOT_OBSERVED_HISTORICAL_ONLY",
            "last_bar_end_label_age_seconds": 1200.0,
            "rows": [{"label": "2026-10-14 14:30", "close": 1.0}],
        }

    def fake_legacy(symbol, *, timeframe, limit):
        calls.append(("legacy", symbol, timeframe, limit))
        return {"status": "PASS", "provider": "TENCENT"}

    ns = {"read_cn_tickflow_research_data": fake_tickflow,
          "read_cn_market_data": fake_legacy}
    exec(compile(ast.fix_missing_locations(
        ast.Module(body=nodes, type_ignores=[])), "<mcp_test>", "exec"), ns)
    return ns["get_cn_market_data"], calls


def test_batch_gets_four_holdings_and_two_periods_in_one_connected_action():
    handler, calls = make_readers()
    response = handler("TICKFLOW:BATCH", timeframe="15m", limit=2)
    assert response["ok"] is True
    assert response["status"] == "PASS_HISTORICAL_ONLY"
    assert response["provider"] == "TICKFLOW_PREMIUM"
    assert response["frame_count"] == 10
    assert response["sequence"] == 9
    assert response["repo_sha"] == "a" * 40
    assert set(response["symbols"]) == {"159611.SZ", "159209.SZ", "518880.SH", "512730.SH", "159363.SZ"}
    assert all(set(p) == {"15m", "60m"} for p in response["symbols"].values())
    assert response["bar_finality"] == "NOT_VERIFIED"
    assert response["radar_admission"] == "BLOCKED"
    assert response["source_arbiter_admission"] == "BLOCKED"
    assert response["live_trade"] is False
    assert response["can_confirm_signal"] is False
    assert response["provider_requests"] == 0
    assert calls == [
        ("159611.SZ", "15m", 2, "historical_only"),
        ("159611.SZ", "60m", 2, "historical_only"),
        ("159209.SZ", "15m", 2, "historical_only"),
        ("159209.SZ", "60m", 2, "historical_only"),
        ("518880.SH", "15m", 2, "historical_only"),
        ("518880.SH", "60m", 2, "historical_only"),
        ("512730.SH", "15m", 2, "historical_only"),
        ("512730.SH", "60m", 2, "historical_only"),
        ("159363.SZ", "15m", 2, "historical_only"),
        ("159363.SZ", "60m", 2, "historical_only"),
    ]


def test_batch_stale_frame_blocks_whole_response_and_never_leaks_partial_rows():
    handler, _ = make_readers(missing=("159209.SZ", "15m"))
    response = handler("TICKFLOW:BATCH", limit=1)
    assert response["ok"] is False
    assert response["status"] == "PARTIAL_OR_STALE"
    assert "symbols" not in response
    assert response["frame_status"]["159209.SZ:15m"] == "STALE"
    assert response["radar_admission"] == "BLOCKED"


def test_batch_misaligned_source_sequence_fails_closed():
    handler, _ = make_readers(different_sequence=("159209.SZ", "60m"))
    response = handler("TICKFLOW:BATCH", limit=1)
    assert response["status"] == "INVALID_SOURCE_ALIGNMENT"
    assert response["ok"] is False
    assert "symbols" not in response


def test_batch_rejects_excessive_limit_and_preserves_normal_cn_route():
    handler, calls = make_readers()
    assert handler("TICKFLOW:BATCH", limit=25)["status"] == "INVALID_REQUEST"
    assert handler("TICKFLOW:BATCH", limit=0)["status"] == "INVALID_REQUEST"
    assert calls == []
    normal = handler("159611.SZ", timeframe="15m", limit=3)
    assert normal == {"status": "PASS", "provider": "TENCENT"}
    assert calls == [("legacy", "159611.SZ", "15m", 3)]
