import ast
import copy
import math
import subprocess
from pathlib import Path

from src.technical import price_structure as shared


ROOT = Path(__file__).parents[1]
FUNCTIONS = (
    "clean_json_value",
    "_dedupe_bars_by_time",
    "_structure_swings",
    "_cluster_levels",
    "_zone_strength",
    "_nearest_zone",
    "_structure_timeframe",
    "build_price_structure_state",
)


def _legacy_namespace():
    source = subprocess.run(
        ["git", "show", "HEAD^:realtime_monitor/server.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    tree = ast.parse(source)
    namespace = {"math": math, "PRICE_STRUCTURE_SCHEMA_VERSION": 1}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            exec(compile(ast.Module([node], []), "legacy_server.py", "exec"), namespace)
    return namespace


def _bars(final_close=None):
    closes = [100 + (i * 2 if i % 2 == 0 else -i) for i in range(40)]
    if final_close is not None:
        closes[-1] = final_close
    return [
        {
            "time_key": f"2026-01-{i + 1:02d}",
            "open": close - 0.25,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
        }
        for i, close in enumerate(closes)
    ]


def _payload(final_close=None):
    bars = _bars(final_close)
    return {
        "symbol": "TEST",
        "generated_at": "2026-01-31T00:00:00+00:00",
        "bars": {"daily": bars, "hourly": copy.deepcopy(bars), "15m": copy.deepcopy(bars)},
        "data_health": {"daily": "OK", "hourly": "OK", "15m": "OK"},
    }


def test_fixed_inputs_match_legacy_implementation():
    legacy = _legacy_namespace()
    cases = [
        _payload(),
        _payload(final_close=140),
        _payload(final_close=60),
        {"symbol": "TEST", "generated_at": "fixed", "bars": {}, "data_health": {}},
        {"symbol": "TEST", "generated_at": "fixed", "bars": {"daily": _bars()[:10]}, "data_health": {"daily": "OK"}},
        {"symbol": "TEST", "generated_at": "fixed", "bars": {"daily": _bars()}, "data_health": {"daily": "STALE"}},
        {"symbol": "TEST", "generated_at": "fixed", "bars": {"daily": _bars() + [_bars()[-1] | {"close": 999}]}, "data_health": {"daily": "OK"}},
        None,
    ]
    for case in cases:
        assert shared.build_price_structure_state(case) == legacy["build_price_structure_state"](case)


def test_differential_cases_cover_wick_only_and_repeated_break_evidence():
    legacy = _legacy_namespace()
    base = _bars()
    wick_only = copy.deepcopy(base)
    wick_only[-1]["high"] = 200
    repeated_close = copy.deepcopy(base)
    repeated_close[-2]["close"] = 200
    repeated_close[-1]["close"] = 201
    for bars in (base, wick_only, repeated_close):
        assert shared._structure_timeframe(bars, "OK", "daily") == legacy["_structure_timeframe"](
            bars, "OK", "daily"
        )


def test_invalid_health_duplicate_and_nonfinite_inputs_fail_closed_identically():
    legacy = _legacy_namespace()
    assert shared._structure_timeframe([], "STALE", "daily") == legacy["_structure_timeframe"]([], "STALE", "daily")
    duplicate = _bars() + [_bars()[-1]]
    conflicting = _bars() + [_bars()[-1] | {"close": 999}]
    for bars in (duplicate, conflicting):
        assert shared._structure_timeframe(bars, "OK", "daily") == legacy["_structure_timeframe"](
            bars, "OK", "daily"
        )
    assert shared.clean_json_value(float("nan")) is None
    assert shared.clean_json_value(float("inf")) is None


def test_server_uses_shared_owner_and_keeps_snapshot_facade():
    source = (ROOT / "realtime_monitor" / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert not defined.intersection(FUNCTIONS)
    assert "from src.technical.price_structure import (" in source
    assert "def get_price_structure_snapshot(" in source


def test_shared_module_has_no_server_or_provider_runtime_imports():
    source = (ROOT / "src" / "technical" / "price_structure.py").read_text(encoding="utf-8")
    assert "realtime_monitor.server" not in source
    assert "futu" not in source
    assert "openai" not in source
    assert "anthropic" not in source
