"""Offline checks for the single-call, budget-metered secure MCP cloud probe."""
from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
import textwrap


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/aws-ssm-ops.yml"


def _cost_probe_source() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("            secure_mcp_cost_smoke)", 1)[1].split(
        "            canonical_futures_mcp_remote_e2e)", 1
    )[0]
    code = block.split('python3 - "$tunnel_id" <<\'PY\'', 1)[1].split(
        "\n          PY", 1
    )[0]
    return textwrap.dedent(code)


def _cost_function():
    tree = ast.parse(_cost_probe_source())
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & {"MODEL", "INPUT_USD_PER_M", "CACHED_INPUT_USD_PER_M", "OUTPUT_USD_PER_M"}:
                keep.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "token_cost":
            keep.append(node)
    ns = {"Decimal": Decimal}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "<cost_probe>", "exec"), ns)
    return ns["token_cost"]


def test_single_call_probe_is_only_one_bounded_responses_request() -> None:
    script = _cost_probe_source()
    assert "max_output_tokens': 3000" in script
    assert script.count("urllib.request.urlopen(") == 1
    assert script.count("https://api.openai.com/v1/responses") == 1
    assert "OPENAI_MODEL_CALLS_ATTEMPTED=1" in script
    assert "OPENAI_MODEL_CALLS_SUCCEEDED=1" in script
    assert "OPENAI_TOKEN_COST_STATUS=UNKNOWN" in script
    assert "CHATGPT_NATIVE_MCP_READ=NOT_VERIFIED" in script
    assert "SOURCE_ARBITER_ADMISSION=BLOCKED" in script
    assert "LIVE_TRADE=NO" in script
    assert "print(payload)" not in script
    assert "print(body)" not in script
    assert "print(req)" not in script
    assert "print(os.environ" not in script


def test_cost_estimate_uses_uncached_cached_and_output_tokens() -> None:
    estimate = _cost_function()(
        {"input_tokens": 10000, "output_tokens": 2000,
         "input_tokens_details": {"cached_tokens": 5000}},
        "gpt-6-astra",
    )
    assert estimate == {
        "input_tokens": 10000,
        "cached_input_tokens": 5000,
        "output_tokens": 2000,
        "usd_token_estimate": "0.155000",
    }


def test_cost_without_cached_tokens() -> None:
    estimate = _cost_function()(
        {"input_tokens": 10000, "output_tokens": 2000}, "gpt-6-astra"
    )
    assert estimate["usd_token_estimate"] == "0.200000"


def test_unknown_usage_or_model_never_fabricates_cost() -> None:
    calc = _cost_function()
    assert calc(None, "gpt-6-astra") is None
    assert calc({"input_tokens": 100, "output_tokens": 20}, "other-model") is None
    assert calc({"input_tokens": 100, "output_tokens": -1}, "gpt-6-astra") is None
    assert calc(
        {"input_tokens": 100, "output_tokens": 20,
         "input_tokens_details": {"cached_tokens": 200}},
        "gpt-6-astra",
    ) is None


def test_new_probe_is_opt_in_not_default_six_call_suite() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "          - secure_mcp_cost_smoke" in workflow
    assert "            secure_mcp_cost_smoke)" in workflow
    assert "            secure_mcp_remote_e2e)" in workflow
    assert "MCP_CALL_SEQUENCE=" in workflow


def test_full_e2e_also_meters_each_call_and_actual_retries() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("            secure_mcp_remote_e2e)", 1)[1].split(
        "            canonical_futures_mcp_remote_e2e)", 1
    )[0]
    assert "OPENAI_HTTP_POST_ATTEMPT=1" in block
    assert "OPENAI_LOGICAL_MODEL_CALLS=" in block
    assert "OPENAI_HTTP200_RESPONSES=" in block
    assert "OPENAI_COST_UNKNOWN_CALLS=" in block
    assert "OPENAI_TOKEN_COST_ESTIMATE_USD=" in block
    assert "OPENAI_CALL_USAGE_" in block
    assert "print(payload)" not in block
    assert "print(req)" not in block


def test_full_e2e_token_estimate_rejects_bad_counts() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("            secure_mcp_remote_e2e)", 1)[1].split(
        "            canonical_futures_mcp_remote_e2e)", 1
    )[0]
    source = textwrap.dedent(
        block.split('python3 - "$tunnel_id" <<\'PY\'', 1)[1].split(
            "\n          PY", 1
        )[0]
    )
    tree = ast.parse(source)
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "response_token_estimate"
    )
    ns = {"Decimal": Decimal}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<full_e2e_cost>", "exec"), ns)
    estimate = ns["response_token_estimate"]
    assert estimate({"model": "gpt-6-astra", "usage": {
        "input_tokens": 10000, "output_tokens": 2000,
        "input_tokens_details": {"cached_tokens": 5000},
    }}) == (10000, 5000, 2000, Decimal("0.155"))
    assert estimate({"model": "gpt-6-astra", "usage": {
        "input_tokens": 100, "output_tokens": -1,
    }}) is None
    assert estimate({"model": "unknown", "usage": {
        "input_tokens": 100, "output_tokens": 20,
    }}) is None


def _typed_diagnostics():
    import json
    source = _cost_probe_source()
    tree = ast.parse(source)
    funcs = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"decode_snapshot_result", "response_diagnostics"}
    ]
    assert len(funcs) == 2
    ns = {"json": json}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), "<typed_mcp>", "exec"), ns)
    return ns["response_diagnostics"]


def test_single_call_diagnostic_classifies_missing_tool_call() -> None:
    inspect = _typed_diagnostics()
    result = inspect({"status": "completed", "output": [
        {"type": "mcp_list_tools", "tools": [{"name": "get_market_snapshots"}]},
    ]})
    assert result["tool_calls"] == 0
    assert result["list_tools"] == 1
    assert result["snapshot_schema"] == "NOT_VERIFIED"
    assert result["market_data_present"] == "NOT_VERIFIED"


def test_single_call_diagnostic_supports_mcp_text_content_envelope() -> None:
    import json
    inspect = _typed_diagnostics()
    data = {
        "read_only": True,
        "snapshots": [
            {"symbol": "AMD", "quote": {"received_at": "2026-10-09T16:00:00Z"}, "bars": []}
        ],
    }
    output = {"content": [{"type": "text", "text": json.dumps(data)}]}
    result = inspect({"status": "completed", "output": [
        {"type": "mcp_call", "name": "get_market_snapshots",
         "status": "completed", "error": None, "output": json.dumps(output)},
    ]})
    assert result["tool_calls"] == 1
    assert result["tool_name_match"] is True
    assert result["tool_error"] is False
    assert result["snapshot_schema"] == "LEGACY_FACADE"
    assert result["market_data_present"] == "PASS"
    assert result["tool_output_shape"] == "SNAPSHOTS_OBJECT"


def test_single_call_diagnostic_rejects_missing_data_or_false_read_only() -> None:
    import json
    inspect = _typed_diagnostics()
    for data in (
        {"read_only": False, "snapshots": [{"symbol": "AMD", "quote": {"price": 1}}]},
        {"read_only": True, "snapshots": [{"symbol": "QQQ", "quote": {"price": 1}}]},
    ):
        result = inspect({"status": "completed", "output": [
            {"type": "mcp_call", "name": "get_market_snapshots",
             "output": json.dumps(data)}
        ]})
        assert result["snapshot_schema"] == "NOT_VERIFIED"
    empty = inspect({"status": "completed", "output": [
        {"type": "mcp_call", "name": "get_market_snapshots",
         "output": json.dumps({
             "read_only": True, "snapshots": [{"symbol": "AMD", "quote": {}, "bars": []}]
         })}
    ]})
    assert empty["snapshot_schema"] == "PASS"
    assert empty["market_data_present"] == "EMPTY"


def test_single_call_diagnostic_never_echoes_provider_error_payloads() -> None:
    inspect = _typed_diagnostics()
    secret = "sensitive_provider_error_with_credentials"
    result = inspect({"status": "completed", "output": [
        {"type": "mcp_call", "name": "get_market_snapshots",
         "error": secret, "output": secret}
    ]})
    assert result["tool_error"] is True
    assert result["tool_output_shape"] == "TEXT_NOT_JSON"
    assert secret not in str(result)
    script = _cost_probe_source()
    assert "print(payload)" not in script
    assert "print(call)" not in script
    assert "print(data)" not in script
    assert "MCP_DIAG_" in script


def test_single_call_diagnostic_rejects_multiple_calls_and_incomplete_response() -> None:
    inspect = _typed_diagnostics()
    one = {"type": "mcp_call", "name": "get_market_snapshots", "output": "{}"}
    multiple = inspect({"status": "completed", "output": [one, one]})
    assert multiple["tool_calls"] == 2
    assert multiple["snapshot_schema"] == "NOT_VERIFIED"
    incomplete = inspect({"status": "incomplete", "output": [one]})
    assert incomplete["response_status"] == "incomplete"
    assert incomplete["snapshot_schema"] == "NOT_VERIFIED"


def _canonical_payload(*, status="PASS", age=8.0, bar=None, live_trade=False, radar="BLOCKED"):
    return {
        "ok": True,
        "status": status,
        "source_age_seconds": age,
        "bar_closure": "PROVEN",
        "radar_admission": radar,
        "live_trade": live_trade,
        "data_available": bar is not False,
        "symbols": {
            "US.AMD": {
                "latest": {
                    "1m": {"time": "2026-10-09T20:00:00Z"},
                    "5m": None,
                    "15m": None if bar is False else (bar or {
                        "time": "2026-10-09T20:00:00Z",
                        "open": 100, "high": 101, "low": 99, "close": 100.5,
                    }),
                    "1h": None,
                }
            }
        },
    }


def test_canonical_snapshot_from_real_cloud_reader_is_accepted() -> None:
    import json
    inspect = _typed_diagnostics()
    data = _canonical_payload()
    result = inspect({"status": "completed", "output": [{
        "type": "mcp_call",
        "name": "get_market_snapshots",
        "status": "completed",
        "output": json.dumps({"content": [{"type": "text", "text": json.dumps(data)}]}),
    }]})
    assert result["tool_output_shape"] == "SYMBOLS_OBJECT"
    assert result["snapshot_schema"] == "PASS"
    assert result["market_data_present"] == "PASS"
    assert result["canonical_source_status"] == "PASS"
    assert result["snapshot_freshness"] == "FRESH"
    assert result["bar_closure"] == "PROVEN"


def test_canonical_snapshot_stale_and_bad_provenance_stay_disqualified() -> None:
    import json
    inspect = _typed_diagnostics()
    for data in (
        _canonical_payload(status="STALE", age=999),
        _canonical_payload(status="PASS", age=None),
        _canonical_payload(status="PASS", live_trade=True),
        _canonical_payload(status="PASS", radar="PASS"),
        _canonical_payload(status="PASS", bar=False),
    ):
        result = inspect({"status": "completed", "output": [{
            "type": "mcp_call", "name": "get_market_snapshots",
            "output": json.dumps(data),
        }]})
        valid_for_smoke = (
            result["snapshot_schema"] == "PASS"
            and result["canonical_source_status"] == "PASS"
            and result["snapshot_freshness"] == "FRESH"
            and result["market_data_present"] == "PASS"
        )
        assert not valid_for_smoke, data


def test_smoke_uses_actual_port_8000_canonical_snapshot_contract() -> None:
    from pathlib import Path
    script = _cost_probe_source()
    canonical = Path("data_provider/us_canonical_runtime_reader.py").read_text(encoding="utf-8")
    server = Path("realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8")
    assert "def get_market_snapshots(symbols: list[str] | None = None)" in server
    assert "return read_us_market_snapshots(symbols)" in server
    assert '"symbols": result' in canonical
    assert '"data_available": any(' in canonical
    assert "symbols.get('US.AMD')" in script
    assert "latest.get('15m')" in script
    assert "do not supply " in script
    assert "snapshot_freshness" in script
    assert "source_age_seconds" in script
