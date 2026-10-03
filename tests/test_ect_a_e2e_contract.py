"""Offline contract coverage for the secure MCP Responses probe."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import urllib.error
import urllib.request

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

    # Match the Responses API wire shape: MCP output is a string; our tools return JSON objects.
    _, wire_failures = validate_response(
        {
            "status_code": 200,
            "output": [_call("get_livefeed_health", output='{"ok":true}')],
        },
        "get_livefeed_health",
        EXPECTED,
        discovered,
    )
    assert wire_failures == []

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
    assert "RESPONSES_ERROR_" in source
    assert "NETWORK_ERROR" in source
    assert "RESPONSE_JSON_ERROR" in source
    assert "SECURE_REMOTE_MCP=PASS" in source


def test_secure_remote_e2e_selector_parses_and_writes_commands_json() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/aws-ssm-ops.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    command_set = next(
        step for step in workflow["jobs"]["read-only-ssm"]["steps"]
        if step.get("id") == "command-set"
    )
    source = str(command_set["run"])

    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if not bash or not jq:
        import pytest

        pytest.skip("bash and jq are required to execute the workflow selector")

    syntax = subprocess.run(
        [bash, "-n"],
        input=source,
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr

    with tempfile.TemporaryDirectory() as directory:
        github_output = Path(directory) / "github_output"
        result = subprocess.run(
            [bash, "-c", source],
            cwd=directory,
            env={
                "PATH": str(Path(jq).parent),
                "REQUESTED_ACTION": "secure_mcp_remote_e2e",
                "GITHUB_OUTPUT": str(github_output),
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        commands = json.loads((Path(directory) / "commands.json").read_text(encoding="utf-8"))
        assert "commands=" in github_output.read_text(encoding="utf-8")

    assert isinstance(commands, list) and len(commands) == 1
    assert "SECURE_REMOTE_MCP=PASS" in commands[0]
    assert "Unsupported action" not in result.stdout


def _response_for_source() -> str:
    workflow = yaml.load(
        (ROOT / ".github/workflows/aws-ssm-ops.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    command_set = next(
        step for step in workflow["jobs"]["read-only-ssm"]["steps"]
        if step.get("id") == "command-set"
    )
    source = str(command_set["run"])
    return source.split("secure_mcp_remote_e2e)", 1)[1].split(
        "secure_mcp_tunnel_deploy)", 1
    )[0].split("python3 - \"$tunnel_id\" <<'PY'", 1)[1].split(
        "\nPY\nREMOTE", 1
    )[0]


def _load_response_for():
    full_source = textwrap.dedent(_response_for_source())
    source = (
        "import json\nimport os\nimport re\nimport urllib.error\nimport urllib.request\n"
        "tunnel_id = 'test-tunnel'\n"
        + full_source[full_source.index("def clean_diagnostic"):full_source.index("def valid_tool_schema")]
    )
    namespace = {
        "json": json,
        "os": __import__("os"),
        "re": re,
        "sys": __import__("sys"),
        "urllib": __import__("urllib"),
    }
    exec(compile(source, "aws-ssm-ops.yml:secure_mcp_remote_e2e", "exec"), namespace)
    return namespace["response_for"]


class _FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, body: bytes):
        super().__init__("https://api.openai.com/v1/responses", 401, "Unauthorized", {}, None)
        self._body = body

    def read(self) -> bytes:
        return self._body


def test_response_for_extracts_redacted_http_error(monkeypatch) -> None:
    secret = "sk-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    body = json.dumps(
        {
            "error": {
                "type": "invalid_request_error",
                "code": "model_not_found",
                "message": "line one\nline two " + secret,
                "param": secret,
            },
            "headers": {"Authorization": "Bearer " + secret},
        }
    ).encode()

    def fail(*args, **kwargs):
        raise _FakeHTTPError(body)

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    response_for = _load_response_for()
    status, payload, diagnostic = response_for("probe", {"get_livefeed_health"})

    assert (status, payload) == (401, None)
    assert diagnostic == {
        "category": "HTTP_ERROR",
        "type": "invalid_request_error",
        "code": "model_not_found",
        "message": "line one line two [REDACTED]",
    }
    output = json.dumps(diagnostic)
    assert "Authorization" not in output
    assert "param" not in output


def test_response_for_non_json_and_safe_categories(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def non_json(*args, **kwargs):
        raise _FakeHTTPError(b"secret body\nAuthorization: Bearer sk-secret")

    monkeypatch.setattr(urllib.request, "urlopen", non_json)
    response_for = _load_response_for()
    assert response_for("probe", set())[2] == {"category": "HTTP_ERROR_NON_JSON"}

    def network_failure(*args, **kwargs):
        raise OSError("https://user:secret@example.test/?api_key=sk-secret")

    monkeypatch.setattr(urllib.request, "urlopen", network_failure)
    assert response_for("probe", set())[2] == {"category": "NETWORK_ERROR"}

    def invalid_json(*args, **kwargs):
        class Response:
            status = 200

            def read(self):
                return b"not-json"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", invalid_json)
    assert response_for("probe", set())[2] == {"category": "RESPONSE_JSON_ERROR"}


def test_response_for_truncates_and_cleans_message(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    message = "a\n\tb" + ("x" * 500)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            _FakeHTTPError(
                json.dumps({"error": {"message": message}}).encode()
            )
        ),
    )
    response_for = _load_response_for()
    diagnostic = response_for("probe", set())[2]
    assert len(diagnostic["message"]) == 400
    assert "\n" not in diagnostic["message"]
    assert "\t" not in diagnostic["message"]
