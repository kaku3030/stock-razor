import ast
import copy
import importlib.util
import json
import math
import subprocess
import sys
import types
from pathlib import Path

from src.technical import price_structure as shared


ROOT = Path(__file__).parents[1]
BASE_SHA = "76526b3c3ca24dacfacf03506b6ac9cc911004ea"
FUNCTIONS = (
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
        ["git", "show", f"{BASE_SHA}:realtime_monitor/server.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    tree = ast.parse(source)
    def clean_json_value(value):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        if isinstance(value, dict):
            return {key: clean_json_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean_json_value(item) for item in value]
        return value

    namespace = {
        "math": math,
        "PRICE_STRUCTURE_SCHEMA_VERSION": 1,
        "clean_json_value": clean_json_value,
    }
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


def _event_bars(*closes):
    values = [
        100, 110, 100, 105, 98, 115, 103, 112, 101, 120,
        106, 118, 104, 125, 110, 123, 108, 130, 114, 128,
        112, 135, 118, 133, 116, 140, 122, 138, 120, 145,
        126, 143, 124, 150, 130, 148, 128, 155, 140,
    ]
    values.extend(closes)
    return [
        {
            "time_key": f"t{i:02d}",
            "open": value,
            "high": value + 1,
            "low": value - 1,
            "close": value,
        }
        for i, value in enumerate(values)
    ]


def _payload(final_close=None):
    bars = _bars(final_close)
    return {
        "symbol": "TEST",
        "generated_at": "2026-01-31T00:00:00+00:00",
        "bars": {"daily": bars, "hourly": copy.deepcopy(bars), "15m": copy.deepcopy(bars)},
        "data_health": {"daily": "OK", "hourly": "OK", "15m": "OK"},
    }


def _without_reference(value):
    if isinstance(value, dict):
        return {
            key: _without_reference(item)
            for key, item in value.items()
            if key not in {"reference_level", "reference_basis", "reference_time"}
        }
    if isinstance(value, list):
        return [_without_reference(item) for item in value]
    return value


def _legacy_timeframe(legacy, bars, health="OK"):
    return legacy["_structure_timeframe"](bars, health, "daily")


def _import_server_with_offline_stubs():
    module_names = (
        "anthropic", "openai", "mcp", "mcp.server", "mcp.server.fastmcp", "futu",
    )
    saved = {name: sys.modules.get(name) for name in module_names}

    class ForbiddenProvider:
        def __init__(self, *args, **kwargs):
            raise AssertionError("offline snapshot attempted provider construction")

    class FakeFastMCP:
        def __init__(self, name):
            self.name = name

        def tool(self):
            return lambda function: function

        def run(self):
            raise AssertionError("offline snapshot attempted MCP run")

    def module(name):
        return types.ModuleType(name)

    anthropic = module("anthropic")
    anthropic.Anthropic = ForbiddenProvider
    anthropic.APIConnectionError = type("APIConnectionError", (Exception,), {})
    anthropic.APIStatusError = type("APIStatusError", (Exception,), {})
    anthropic.APITimeoutError = type("APITimeoutError", (Exception,), {})

    openai = module("openai")
    openai.OpenAI = ForbiddenProvider
    openai.APIConnectionError = type("APIConnectionError", (Exception,), {})
    openai.APIStatusError = type("APIStatusError", (Exception,), {})
    openai.APITimeoutError = type("APITimeoutError", (Exception,), {})

    mcp = module("mcp")
    mcp_server = module("mcp.server")
    mcp_fastmcp = module("mcp.server.fastmcp")
    mcp_fastmcp.FastMCP = FakeFastMCP
    mcp.server = mcp_server
    mcp_server.fastmcp = mcp_fastmcp

    futu = module("futu")
    futu.OpenQuoteContext = ForbiddenProvider
    futu.OpenSecTradeContext = ForbiddenProvider
    for name in ("TrdMarket", "TrdEnv", "SecurityFirm", "SubType", "KLType", "Market"):
        setattr(futu, name, types.SimpleNamespace(US="US", FUTUJP="FUTUJP"))
    futu.RET_OK = 0

    sys.modules.update({
        "anthropic": anthropic,
        "openai": openai,
        "mcp": mcp,
        "mcp.server": mcp_server,
        "mcp.server.fastmcp": mcp_fastmcp,
        "futu": futu,
    })
    try:
        path = ROOT / "realtime_monitor" / "server.py"
        spec = importlib.util.spec_from_file_location("offline_server_regression", path)
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        return loaded
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_fixed_inputs_match_fixed_parent_implementation():
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
        actual = _without_reference(shared.build_price_structure_state(case))
        expected = legacy["build_price_structure_state"](case)
        assert actual == expected


def test_breakout_breakdown_and_retest_emit_reference_level_basis_and_time():
    breakout = shared._structure_timeframe(_event_bars(160), "OK", "daily")
    assert breakout["state"] == "BREAKOUT"
    assert breakout["reference_level"] == 151.0
    assert breakout["reference_basis"] == "LATEST_CONFIRMED_SWING_HIGH"
    assert breakout["reference_time"] == "t33"

    breakdown = shared._structure_timeframe(_event_bars(80), "OK", "daily")
    assert breakdown["state"] == "STRUCTURE_DAMAGED"
    assert "BREAKDOWN_BELOW_SUPPORT" in breakdown["reason_codes"]
    assert breakdown["reference_level"] == 127.0
    assert breakdown["reference_basis"] == "LATEST_CONFIRMED_SWING_LOW"
    assert breakdown["reference_time"] == "t36"

    retest = shared._structure_timeframe(_event_bars(160, 146), "OK", "daily")
    assert retest["state"] == "RETEST"
    assert retest["reference_level"] == 146.0
    assert retest["reference_basis"] == "PREVIOUS_CONFIRMED_SWING_HIGH"
    assert retest["reference_time"] == "t29"


def test_fixed_sha_event_branches_match_legacy_common_contract():
    legacy = _legacy_namespace()
    wick_only = _event_bars(140)
    wick_only[-1]["high"] = 220
    cases = [
        (_event_bars(160), "BREAKOUT"),
        (_event_bars(80), "STRUCTURE_DAMAGED"),
        (_event_bars(160, 146), "RETEST"),
        (wick_only, "PULLBACK"),
        (_event_bars(160, 170), "UPTREND"),
    ]
    for bars, expected_state in cases:
        actual = shared._structure_timeframe(bars, "OK", "daily")
        expected = _legacy_timeframe(legacy, bars, "OK")
        assert actual["state"] == expected_state
        assert _without_reference(actual) == expected

    assert "BREAKOUT_ABOVE_RESISTANCE" in _legacy_timeframe(
        legacy, _event_bars(160), "OK")["reason_codes"]
    assert "BREAKDOWN_BELOW_SUPPORT" in _legacy_timeframe(
        legacy, _event_bars(80), "OK")["reason_codes"]
    assert "RETESTING_BREAKOUT_LEVEL" in _legacy_timeframe(
        legacy, _event_bars(160, 146), "OK")["reason_codes"]



def test_breakout_is_close_cross_only_and_does_not_repeat():
    wick_only = _event_bars(140)
    wick_only[-1]["high"] = 220
    assert "BREAKOUT_ABOVE_RESISTANCE" not in shared._structure_timeframe(wick_only, "OK", "daily")["reason_codes"]

    first = shared._structure_timeframe(_event_bars(160), "OK", "daily")
    repeated = shared._structure_timeframe(_event_bars(160, 170), "OK", "daily")
    assert first["state"] == "BREAKOUT"
    assert repeated["state"] != "BREAKOUT"
    assert "BREAKOUT_ABOVE_RESISTANCE" not in repeated["reason_codes"]


def test_duplicate_timestamp_conflicts_and_data_quality_fail_closed():
    duplicate = _event_bars(140)
    duplicate.append(copy.deepcopy(duplicate[-1]))
    conflicting = _event_bars(140)
    conflicting.append(duplicate[-1] | {"close": 999})
    identical_result = shared._structure_timeframe(duplicate, "OK", "daily")
    assert "CONFLICTING_DUPLICATE_TIMESTAMP" not in identical_result["reason_codes"]
    result = shared._structure_timeframe(conflicting, "OK", "daily")
    assert result["state"] == "INDETERMINATE"
    assert "CONFLICTING_DUPLICATE_TIMESTAMP" in result["reason_codes"]

    limited = shared._structure_timeframe(_event_bars(160), "STALE", "daily")
    assert limited["state"] == "INDETERMINATE"
    assert limited["reason_codes"] == ["DATA_HEALTH_LIMITED"]
    invalid = shared.build_price_structure_state(None)
    assert invalid["primary_structure"] == "INDETERMINATE"
    assert invalid["reason_codes"] == ["INVALID_STRUCTURE_INPUT"]


def test_repeated_calls_are_deterministic_and_new_fields_are_neutral_when_no_event():
    bars = _event_bars(140)
    first = shared._structure_timeframe(bars, "OK", "daily")
    second = shared._structure_timeframe(copy.deepcopy(bars), "OK", "daily")
    assert first == second
    assert first["reference_level"] is None
    assert first["reference_basis"] is None
    assert first["reference_time"] is None


def test_server_keeps_json_boundary_and_snapshot_facade():
    source = (ROOT / "realtime_monitor" / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert not defined.intersection({"_dedupe_bars_by_time", "_structure_swings", "_cluster_levels", "_zone_strength", "_nearest_zone", "_structure_timeframe", "build_price_structure_state"})
    assert "def clean_json_value(value):" in source
    assert "from src.technical.price_structure import (" in source
    assert "return clean_json_value(snapshot)" in source
    assert "def get_price_structure_snapshot(" in source


def test_shared_module_has_no_json_cleaner_or_runtime_imports():
    source = (ROOT / "src" / "technical" / "price_structure.py").read_text(encoding="utf-8")
    assert "def clean_json_value" not in source
    assert "realtime_monitor.server" not in source
    assert "futu" not in source
    assert "openai" not in source
    assert "anthropic" not in source


def test_snapshot_facade_runs_offline_with_controlled_dependencies():
    server = _import_server_with_offline_stubs()
    calls = []
    bars = _event_bars(160)

    def fake_get_bars(symbol, timeframe, count):
        calls.append(("get_bars", symbol, timeframe, count))
        return {"ok": True, "data": copy.deepcopy(bars)}

    def fake_health(symbol, timeframe):
        calls.append(("data_health_check", symbol, timeframe))
        return {"status": "OK"}

    server.get_bars = fake_get_bars
    server.data_health_check = fake_health
    snapshot = server.get_price_structure_snapshot("US.TEST", count=1)

    assert calls == [
        ("get_bars", "US.TEST", "1d", 120),
        ("data_health_check", "US.TEST", "1d"),
        ("get_bars", "US.TEST", "1h", 120),
        ("data_health_check", "US.TEST", "1h"),
        ("get_bars", "US.TEST", "15m", 120),
        ("data_health_check", "US.TEST", "15m"),
    ]
    assert snapshot["symbol"] == "US.TEST"
    assert set(snapshot) >= {"schema_version", "timeframes", "data_health"}
    assert snapshot["timeframes"]["daily"]["state"] == "BREAKOUT"
    json.dumps(snapshot, allow_nan=False)
    assert server.clean_json_value(float("nan")) is None

    server.data_health_check = lambda symbol, timeframe: {"status": "STALE"}
    limited = server.get_price_structure_snapshot("US.TEST", count=1)
    assert all(
        frame["state"] == "INDETERMINATE"
        and "DATA_HEALTH_LIMITED" in frame["reason_codes"]
        for frame in limited["timeframes"].values()
    )
    json.dumps(limited, allow_nan=False)


def test_reference_level_preserves_raw_decision_price_and_swing_bar_time():
    bars = _event_bars(160)
    bars[33]["high"] = 151.234567
    result = shared._structure_timeframe(bars, "OK", "daily")
    assert result["state"] == "BREAKOUT"
    assert "BREAKOUT_ABOVE_RESISTANCE" in result["reason_codes"]
    assert result["reference_level"] == bars[33]["high"]
    assert result["reference_level"] != round(bars[33]["high"], 2)
    assert result["reference_basis"] == "LATEST_CONFIRMED_SWING_HIGH"
    assert result["reference_time"] == bars[33]["time_key"]
    assert result["reference_time"] == "t33"  # swing bar, not confirmation/availability
    legacy = _legacy_timeframe(_legacy_namespace(), bars)
    assert _without_reference(result) == legacy


def test_legacy_snapshot_exact_shape_and_neutral_interface_separate():
    server = _import_server_with_offline_stubs()
    bars = _event_bars(160)
    calls = []

    def fake_bars(symbol, timeframe, count):
        calls.append((symbol, timeframe, count))
        return {"ok": True, "data": copy.deepcopy(bars)}

    server.get_bars = fake_bars
    server.data_health_check = lambda symbol, timeframe: {"status": "OK"}
    actual = server.get_price_structure_snapshot("US.TEST", count=1)
    assert calls == [("US.TEST", timeframe, 120) for timeframe in ("1d", "1h", "15m")]
    legacy_input = {
        "generated_at": actual["generated_at"], "symbol": "US.TEST",
        "bars": {name: copy.deepcopy(bars) for name in ("daily", "hourly", "15m")},
        "data_health": {name: "OK" for name in ("daily", "hourly", "15m")},
    }
    expected = _legacy_namespace()["build_price_structure_state"](legacy_input)
    assert actual == expected  # full nested shape, no fields stripped from either side
    assert all(not ({"reference_level", "reference_basis", "reference_time"} & set(frame))
               for frame in actual["timeframes"].values())
    neutral = shared.build_price_structure_state(legacy_input)
    assert neutral["timeframes"]["daily"]["reference_level"] == 151.0
    assert neutral["timeframes"]["daily"]["reference_time"] == "t33"
    assert neutral["timeframes"]["daily"]["reference_basis"] == "LATEST_CONFIRMED_SWING_HIGH"
    json.dumps(actual, allow_nan=False)
