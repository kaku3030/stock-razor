"""Offline guard for the 8-slot OpenD temporary multi-timeframe stress scope."""
from pathlib import Path
import ast

from scripts.benchmark_opend_owned_multitimeframe import safe_bars, percentile


def test_source_scope_and_no_trading_or_history_quota():
    s=Path("scripts/benchmark_opend_owned_multitimeframe.py").read_text("utf8")
    w=Path(".github/workflows/benchmark-opend-owned-multitimeframe.yml").read_text("utf8")
    t=ast.parse(s)
    calls={n.func.attr for n in ast.walk(t)
           if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert "subscribe" in calls and "get_cur_kline" in calls
    assert not {"place_order","unlock_trade","get_history_kline",
                "request_history_kline","unsubscribe_all","restart"} & calls
    assert 'FRAME_TYPES = ("5m", "15m", "60m", "1d")' in s
    assert "MIN_REMAIN = 12" in s and "MAX_CALLS = 60" in s
    assert 'ctx.close()' in s
    assert "ft.SubType.K_5M" in s and "ft.SubType.K_15M" in s
    assert "ft.SubType.K_60M" in s and "ft.SubType.K_DAY" in s
    assert ".temporary_subscriptions_established<=8" in w
    assert ".valid_depth_calls>=32" in w
    assert "length)==8" in w
    assert 'split("\\n")' in w and 'split("\\\\n")' not in w


def test_quality_and_missing_percentile_remain_fail_closed():
    class Fake:
        def to_dict(self,*,orient):
            assert orient=="records"
            return [{"time_key":"2026-10-14 10:00:00",
                     "open":10.0,"high":11.0,"low":9.5,
                     "close":10.0,"volume":100}]
    assert safe_bars(Fake())["status"]=="PASS"
    assert percentile([],95) is None
