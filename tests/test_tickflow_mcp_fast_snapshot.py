"""Opt-in compact cloud TickFlow watchlist through the already-connected MCP action."""
import ast
import json
from pathlib import Path


def _handler(*, status="PASS_HISTORICAL_ONLY", misalign=False):
    source=Path("realtime_monitor/readonly_mcp_server.py").read_text("utf-8")
    tree=ast.parse(source)
    wanted=("_read_tickflow_historical_batch","_read_tickflow_fast_snapshot",
            "get_cn_market_data")
    nodes=[]
    for name in wanted:
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        node.decorator_list=[]
        nodes.append(node)
    calls=[]
    def research(symbol,*,timeframe,limit,research_mode):
        calls.append((symbol,timeframe,limit,research_mode))
        return {
            "ok": status=="PASS_HISTORICAL_ONLY",
            "status": status,"research_only":True,
            "radar_admission":"BLOCKED","source_arbiter_admission":"BLOCKED",
            "bar_finality":"NOT_VERIFIED","live_trade":False,
            "provider_requests":0,"repo_sha":"b"*40,
            "sequence":5+int(misalign and symbol=="159209.SZ" and timeframe=="60m"),
            "source_age_seconds":30.2,
            "last_bar_end_label_age_seconds":500.0,
            "expected_grid_progress":"DUE_LABEL_NOT_OBSERVED_HISTORICAL_ONLY",
            "rows":[{
                "label":"2026-10-14 14:30",
                "open":1.5999999999999994,"high":1.6,
                "low":1.598,"close":1.5999999999999994,
                "volume":12345,"amount":32100.0,
                "amount_availability":"PRESENT_UNVERIFIED",
                "ohlc_validation":"VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY",
                "is_partial_bar":True,"bar_finality":"NOT_VERIFIED",
            }],
        }
    def legacy(symbol,*,timeframe,limit):
        calls.append(("legacy",symbol,timeframe,limit))
        return {"status":"PASS","provider":"TENCENT"}
    ns={"read_cn_tickflow_research_data":research,"read_cn_market_data":legacy}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),
                 "<isolated-mcp>", "exec"),ns)
    return ns["get_cn_market_data"],calls


def test_fast_returns_bounded_native_ohlcv_and_quality_not_live_admission():
    h,calls=_handler()
    fast=h("TICKFLOW:FAST",limit=60,timeframe="1d")
    assert fast["status"]=="PASS_HISTORICAL_ONLY"
    assert fast["ok"] is True
    assert fast["provider"]=="TICKFLOW_PREMIUM"
    assert fast["read_scope"]=="CLOUD_MCP_LOCAL_CACHE_NOT_CHATGPT_RTT"
    assert fast["read_ms"]>=0
    assert fast["frame_count"]==10
    assert fast["repo_sha"]=="b"*40 and fast["sequence"]==5
    assert fast["research_only"] is True and fast["provider_requests"]==0
    assert fast["live_trade"] is False and fast["radar_admission"]=="BLOCKED"
    assert fast["bar_finality"]=="NOT_VERIFIED"
    assert fast["source_arbiter_admission"]=="BLOCKED"
    assert fast["can_confirm_signal"] is False
    assert set(fast["symbols"])=={"159611.SZ","159209.SZ","518880.SH","512730.SH","159363.SZ"}
    assert all(set(v)=={"15m","60m"} for v in fast["symbols"].values())
    for frames in fast["symbols"].values():
        for row in frames.values():
            assert row["o"]==1.5999999999999994
            assert row["c"]==1.5999999999999994
            assert row["ohlc_validation"]=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
            assert row["is_partial_bar"] is True
            assert row["bar_finality"]=="NOT_VERIFIED"
            assert row["expected_grid_progress"]=="DUE_LABEL_NOT_OBSERVED_HISTORICAL_ONLY"
    assert len(calls)==10
    assert all(call[2:]==(1,"historical_only") for call in calls)
    full=h("TICKFLOW:BATCH",limit=1)
    assert len(json.dumps(fast,separators=(",",":")))<len(json.dumps(full,separators=(",",":")))


def test_fast_stale_blocks_all_price_fields():
    h,calls=_handler(status="STALE")
    result=h("TICKFLOW:FAST")
    assert result["ok"] is False
    assert result["status"]=="PARTIAL_OR_STALE"
    assert "symbols" not in result
    assert result["provider_requests"]==0 and result["live_trade"] is False
    assert len(calls)==1


def test_fast_sequence_mismatch_fails_closed_and_normal_route_unchanged():
    h,calls=_handler(misalign=True)
    result=h("TICKFLOW:FAST",limit=1)
    assert result["status"]=="INVALID_SOURCE_ALIGNMENT"
    assert "symbols" not in result
    normal=h("159611.SZ",timeframe="15m",limit=3)
    assert normal=={"status":"PASS","provider":"TENCENT"}
    assert calls[-1]==("legacy","159611.SZ","15m",3)
