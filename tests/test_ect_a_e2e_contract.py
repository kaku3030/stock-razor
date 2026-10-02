"""Offline contract coverage for the secure MCP Responses probe."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "get_livefeed_health",
    "get_market_snapshots",
    "get_market_bars",
}


def valid_tool_schema(tool: object) -> bool:
    if not isinstance(tool, dict):
        return False
    schema = tool.get("input_schema")
    return (
        isinstance(tool.get("name"), str)
        and isinstance(schema, dict)
        and schema.get("type") in (None, "object")
    )


def valid_call_output(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("error") not in (None, "") or "output" not in item:
        return False
    value = item["output"]
    if isinstance(value, str):
        if not value.strip():
            return False
        try:
            value = json.loads(value)
        except ValueError:
            return False
    if not isinstance(value, (dict, list)):
        return False
    return not (
        isinstance(value, dict)
        and (value.get("error") is not None or value.get("isError") is True)
    )


def validate_response(
    payload: object,
    expected_name: str,
    allowed: set[str],
    discovered: list[str] | None,
) -> tuple[list[str] | None, list[str]]:
    failures: list[str] = []
    if not isinstance(payload, dict) or payload.get("status_code") != 200:
        return discovered, ["responses-http-or-json"]
    output = payload.get("output")
    if not isinstance(output, list):
        return discovered, ["output-not-list"]
    for item in [item for item in output if item.get("type") == "mcp_list_tools"]:
        tools = item.get("tools")
        names = [tool.get("name") for tool in tools] if isinstance(tools, list) else None
        if (
            not isinstance(tools, list)
            or len(names) != len(set(names))
            or not all(valid_tool_schema(tool) for tool in tools)
        ):
            failures.append("tool-discovery-schema")
        elif discovered is None:
            if len(names) != 3 or set(names) != EXPECTED:
                failures.append("tool-discovery-incomplete")
            else:
                discovered = names
        elif not set(names).issubset(allowed):
            failures.append("allowed-tools-mismatch")
    calls = [item for item in output if item.get("type") == "mcp_call"]
    if len(calls) != 1:
        failures.append("call-count")
    elif calls[0].get("name") != expected_name or not valid_call_output(calls[0]):
        failures.append("call-name-or-output")
    return discovered, failures


def _call(name: str, *, error: object = None, output: object = {"ok": True}) -> dict:
    return {"type": "mcp_call", "name": name, "error": error, "output": output}


def _listed(names: list[str], *, missing_schema: bool = False) -> dict:
    tools = []
    for name in names:
        tool = {"name": name, "input_schema": {"type": "object"}}
        if missing_schema and name == names[0]:
            del tool["input_schema"]
        tools.append(tool)
    return {"type": "mcp_list_tools", "tools": tools}


def test_valid_discovery_and_allowed_single_tool_flow() -> None:
    discovered, failures = validate_response(
        {
            "status_code": 200,
            "output": [_listed(sorted(EXPECTED)), _call("get_livefeed_health")],
        },
        "get_livefeed_health",
        EXPECTED,
        None,
    )
    assert failures == []
    assert discovered is not None and set(discovered) == EXPECTED

    discovered, failures = validate_response(
        {
            "status_code": 200,
            "output": [_listed(["get_market_bars"]), _call("get_market_bars")],
        },
        "get_market_bars",
        {"get_market_bars"},
        discovered,
    )
    assert failures == []


def test_discovery_rejects_wrong_missing_extra_and_missing_schema() -> None:
    for names in (
        ["get_livefeed_health", "get_market_snapshots"],
        [*sorted(EXPECTED), "unexpected"],
        ["get_livefeed_health", "get_market_snapshots", "unexpected"],
    ):
        _, failures = validate_response(
            {"status_code": 200, "output": [_listed(names), _call("get_livefeed_health")]},
            "get_livefeed_health",
            EXPECTED,
            None,
        )
        assert "tool-discovery-incomplete" in failures
    _, failures = validate_response(
        {
            "status_code": 200,
            "output": [_listed(sorted(EXPECTED), missing_schema=True), _call("get_livefeed_health")],
        },
        "get_livefeed_health",
        EXPECTED,
        None,
    )
    assert "tool-discovery-schema" in failures


def test_call_rejects_wrong_name_status_and_output() -> None:
    for call in (
        _call("wrong_tool"),
        _call("get_livefeed_health", error={"type": "mcp_tool_error", "message": "failed"}),
        {"type": "mcp_call", "name": "get_livefeed_health", "error": None, "output": {"ok": True}},
        _call("get_livefeed_health", output=""),
        _call("get_livefeed_health", output="{malformed}"),
        _call("get_livefeed_health", output=object()),
        _call("get_livefeed_health", output={"isError": True}),
    ):
        _, failures = validate_response(
            {"status_code": 200, "output":[_call("get_livefeed_health"), call]},
            "get_livefeed_health",
            EXPECTED,
            sorted(EXPECTED),
        )
        assert "call-count" in failures

    for call in (
        _call("wrong_tool"),
        _call("get_livefeed_health", error={"type": "mcp_tool_error", "message": "failed"}),
        _call("get_livefeed_health", error="failed"),
        _call("get_livefeed_health", output=""),
        _call("get_livefeed_health", output="{malformed}"),
        _call("get_livefeed_health", output=object()),
        _call("get_livefeed_health", output={"isError": True}),
    ):
        _, failures = validate_response(
            {"status_code": 200, "output":[call]},
            "get_livefeed_health",
            EXPECTED,
            sorted(EXPECTED),
        )
        assert "call-name-or-output" in failures


def test_http_responses_error_fails_closed() -> None:
    for payload in ({"status_code": 401}, {"status_code": 500, "output": []}, None):
        _, failures = validate_response(payload, "get_livefeed_health", EXPECTED, None)
        assert failures == ["responses-http-or-json"]


def test_workflow_contains_fail_closed_contract() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/aws-ssm-ops.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    command_set = next(
        step for step in workflow["jobs"]["read-only-ssm"]["steps"]
        if step.get("id") == "command-set"
    )
    source = str(command_set["run"])
    source = source.split("secure_mcp_remote_e2e)", 1)[1].split(
        "secure_mcp_tunnel_deploy)", 1
    )[0]
    assert "input_schema" in source
    assert "inputSchema" not in source
    assert "item.get('status')" not in source
    assert "item.get('error') not in (None, '')" in source
    assert "set(names).issubset(allowed)" in source
    assert "SECURE_REMOTE_MCP=PASS" in source
