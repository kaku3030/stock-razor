"""Unit/static guards for offline real technical engine CPU benchmark."""
from pathlib import Path
import ast

from scripts.benchmark_us_radar_actual_compute_readonly import percentile

def test_percentile_examples():
    assert percentile([],95) is None
    assert percentile([1,2,3,4,5],50)==3
    assert percentile([1,2,3,4,5],95)==4.8


def test_radar_benchmark_no_provider_or_worker_writes():
    source = Path("scripts/benchmark_us_radar_actual_compute_readonly.py").read_text("utf-8")
    assert "ITERATIONS = 25" in source
    assert "load_canonical_snapshot_file(CANONICAL)" in source
    assert "svc.evaluate(s, daily=cached_daily.get(s.symbol))" in source
    assert "PASS_ISOLATED_REPLAY" in source
    tree = ast.parse(source)
    method_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not {"subscribe","unsubscribe","place_order","write_text",
                "write_bytes","publish","send_order","request_history_kline",
                "send_command"} & method_calls
