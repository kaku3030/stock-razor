"""Offline guards for the temporary own-connection OpenD performance probe."""
from pathlib import Path
import ast

from scripts.benchmark_opend_owned_connection_readonly import percentile, safe_bars


class FakeBars:
    def __init__(self, rows):
        self.rows=rows

    def to_dict(self, *, orient):
        assert orient == "records"
        return self.rows


def row(ts="2026-10-14 09:30:00"):
    return {"time_key":ts,"open":10.0,"high":11.0,"low":9.5,"close":10.5,"volume":100}


def test_observations_validate_bars_and_fail_closed():
    assert safe_bars(FakeBars([row()]))["status"]=="PASS"
    assert safe_bars(FakeBars([row(),row()]))["duplicate_rows"]==1
    bad=row()
    bad["low"]=10.9
    assert safe_bars(FakeBars([bad]))["status"]=="QUALITY_BLOCKED"
    assert safe_bars(FakeBars([]))["status"]=="EMPTY_DATA"


def test_percentile_and_no_native_success_is_not_zero_ms():
    assert percentile([],50) is None
    assert percentile([10.,20.,30.],50)==20.0
    assert percentile([10.,20.,30.],95)==29.0


def test_quota_guard_only_own_context_and_no_trades_or_history():
    code=Path("scripts/benchmark_opend_owned_connection_readonly.py").read_text("utf8")
    workflow=Path(".github/workflows/benchmark-opend-owned-connection-readonly.yml").read_text("utf8")
    tree=ast.parse(code)
    calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert "subscribe" in calls and "get_cur_kline" in calls
    assert not {"place_order","unlock_trade","get_history_kline","unsubscribe_all","stop","restart","send_command"} & calls
    assert "is_all_conn=False" in code
    assert "MIN_REMAIN = 4" in code and "MAX_CALLS = 30" in code
    assert "ctx.close()" in code
    assert ".temporary_context_closed==true" in workflow
    assert '.status=="PASS_NATIVE"' in workflow
    assert 'split("\\n")' in workflow
    assert 'split("\\\\n")' not in workflow
