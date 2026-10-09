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
        "            secure_mcp_remote_e2e)", 1
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
    assert "MCP_CALL_SEQUENCE=PASS" in workflow


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
