"""One call for four holdings × five TickFlow cloud research periods, never live admission."""
import ast
from pathlib import Path


def make_dispatch(*, stale=None, misalign=None):
    code=Path("realtime_monitor/readonly_mcp_server.py").read_text("utf-8")
    tree=ast.parse(code)
    nodes=[]
    for name in ("_read_tickflow_historical_batch","get_cn_market_data"):
        n=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name==name)
        n.decorator_list=[]
        nodes.append(n)
    calls=[]
    def tickflow(symbol,*,timeframe,limit,research_mode):
        calls.append((symbol,timeframe,limit,research_mode))
        status="STALE" if (symbol,timeframe)==stale else "PASS_HISTORICAL_ONLY"
        return {"ok":status=="PASS_HISTORICAL_ONLY","status":status,
            "provider":"TICKFLOW_PREMIUM","repo_sha":"f"*40,
            "sequence":7+int((symbol,timeframe)==misalign),
            "research_only":True,"radar_admission":"BLOCKED",
            "source_arbiter_admission":"BLOCKED","live_trade":False,
            "bar_finality":"NOT_VERIFIED","provider_requests":0,
            "source_age_seconds":5.0,"expected_grid_progress":"DUE_LABEL_PRESENT_NOT_FINALITY_PROOF",
            "last_bar_end_label_age_seconds":700.0,
            "rows":[{"label":"2026-10-14 15:00","close":1.59,
                     "ohlc_validation":"STRICT",
                     "bar_finality":"NOT_VERIFIED","is_partial_bar":True}]}
    def legacy(symbol,*,timeframe,limit):
        calls.append(("legacy",symbol,timeframe,limit))
        return {"provider":"TENCENT"}
    ns={"read_cn_tickflow_research_data":tickflow,"read_cn_market_data":legacy}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),
                 "<isolated>", "exec"),ns)
    return ns["get_cn_market_data"],calls


def test_full_one_call_twenty_bounded_research_frames():
    h,calls=make_dispatch()
    res=h("TICKFLOW:FULL",limit=40)
    assert res["status"]=="PASS_HISTORICAL_ONLY"
    assert res["provider"]=="TICKFLOW_PREMIUM"
    assert res["frame_count"]==25
    assert res["repo_sha"]=="f"*40 and res["sequence"]==7
    assert res["bar_finality"]=="NOT_VERIFIED"
    assert res["radar_admission"]=="BLOCKED"
    assert res["source_arbiter_admission"]=="BLOCKED"
    assert res["live_trade"] is False and res["provider_requests"]==0
    assert set(res["symbols"])=={"159611.SZ","159209.SZ","518880.SH","512730.SH","159363.SZ"}
    assert all(set(v)=={"1m","5m","15m","60m","1d"} for v in res["symbols"].values())
    assert len(calls)==25
    assert all(x[2:]==(40,"historical_only") for x in calls)
    assert h("TICKFLOW:BATCH",limit=1)["frame_count"]==10
    assert len(calls)==35
    assert h("TICKFLOW:BATCH",limit=25)["status"]=="INVALID_REQUEST"
    assert h("TICKFLOW:FULL",limit=241)["status"]=="INVALID_REQUEST"
    assert h("TICKFLOW:FULL",limit=0)["status"]=="INVALID_REQUEST"
    assert len(calls)==35


def test_full_stale_or_misaligned_frame_fails_entire_result():
    for params,expected in (({"stale":("159209.SZ","5m")},"PARTIAL_OR_STALE"),
                            ({"misalign":("159209.SZ","1d")},"INVALID_SOURCE_ALIGNMENT")):
        h,calls=make_dispatch(**params)
        r=h("TICKFLOW:FULL",limit=1)
        assert r["status"]==expected and r["ok"] is False
        assert "symbols" not in r
        assert r["radar_admission"]=="BLOCKED"
        assert r["live_trade"] is False


def test_normal_cn_data_route_unmodified_and_no_extra_research_calls():
    h,calls=make_dispatch()
    assert h("159611.SZ",timeframe="15m",limit=30)=={"provider":"TENCENT"}
    assert calls==[("legacy","159611.SZ","15m",30)]
