"""Tests for the bounded rate-limit handling in the secure MCP probe."""

from __future__ import annotations

import ast
import io
import json
import math
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/aws-ssm-ops.yml"
SECRET = "test-secret-must-not-leak"


def _script_source() -> str:
    source = WORKFLOW.read_text(encoding="utf-8")
    start = source.index('python3 - "$tunnel_id" <<\'PY\'') + len(
        'python3 - "$tunnel_id" <<\'PY\''
    )
    end = source.index("\n          PY", start)
    return textwrap.dedent(source[start:end])


def _probe_namespace(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    tree = ast.parse(_script_source())
    namespace: dict[str, object] = {
        "json": json,
        "math": math,
        "os": SimpleNamespace(environ={"OPENAI_API_KEY": SECRET}),
        "re": __import__("re"),
        "time": SimpleNamespace(sleep=lambda _seconds: None),
        "urllib": SimpleNamespace(error=urllib.error, request=urllib.request),
        "tunnel_id": "test-tunnel",
        "RETRY_AFTER_FALLBACK_SECONDS": 25,
        "RETRY_AFTER_MAX_SECONDS": 60,
    }
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    code = compile(ast.Module(body=functions, type_ignores=[]), str(WORKFLOW), "exec")
    exec(code, namespace)
    return namespace


class _Response:
    status = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


def _http_error(
    status: int,
    *,
    retry_after: str | None = None,
    message: str = "rate limited",
) -> urllib.error.HTTPError:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    body = json.dumps(
        {"error": {"type": "requests", "code": "rate_limit_exceeded", "message": message}}
    ).encode()
    return urllib.error.HTTPError(
        "https://api.openai.com/v1/responses",
        status,
        "response error",
        headers,
        io.BytesIO(body),
    )


def _run_response_for(
    monkeypatch: pytest.MonkeyPatch,
    errors_or_response: list[object],
) -> tuple[tuple[object, object, object], list[float]]:
    namespace = _probe_namespace(monkeypatch)
    sleeps: list[float] = []
    namespace["time"] = SimpleNamespace(sleep=sleeps.append)
    outcomes = iter(errors_or_response)

    def fake_urlopen(_request: object, timeout: int) -> object:
        assert timeout == 90
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = namespace["response_for"](
        "test instruction", {"get_market_snapshots"}
    )
    return result, sleeps


def test_429_valid_retry_after_sleeps_once_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, sleeps = _run_response_for(
        monkeypatch,
        [_http_error(429, retry_after="20"), _Response({"output": []})],
    )

    assert result[0] == 200
    assert sleeps == [20.0]


@pytest.mark.parametrize("retry_after", [None, "invalid", "-1", "nan"])
def test_429_missing_or_invalid_retry_after_uses_fallback(
    monkeypatch: pytest.MonkeyPatch,
    retry_after: str | None,
) -> None:
    result, sleeps = _run_response_for(
        monkeypatch,
        [_http_error(429, retry_after=retry_after), _Response({"output": []})],
    )

    assert result[0] == 200
    assert sleeps == [25]


def test_429_twice_returns_final_diagnostic_without_retry_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, sleeps = _run_response_for(
        monkeypatch,
        [
            _http_error(429, retry_after="20"),
            _http_error(429, retry_after="20", message=SECRET),
        ],
    )

    assert result[0] == 429
    assert result[1] is None
    assert result[2]["code"] == "rate_limit_exceeded"
    assert SECRET not in json.dumps(result[2])
    assert sleeps == [20.0]


def test_non_429_http_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    result, sleeps = _run_response_for(
        monkeypatch,
        [_http_error(500, retry_after="20")],
    )

    assert result[0] == 500
    assert sleeps == []


def test_retry_after_is_clamped_to_maximum(monkeypatch: pytest.MonkeyPatch) -> None:
    result, sleeps = _run_response_for(
        monkeypatch,
        [_http_error(429, retry_after="999"), _Response({"output": []})],
    )

    assert result[0] == 200
    assert sleeps == [60]


def test_workflow_keeps_sensitive_request_data_out_of_diagnostics() -> None:
    source = _script_source()

    assert "Retry-After" in source
    assert "Authorization" in source
    assert "REQUEST_PACING_SECONDS = 25" in source
    assert "time.sleep(REQUEST_PACING_SECONDS)" in source
    assert "print('RESPONSES_ERROR_'" in source
    assert "print(exc.headers" not in source
    assert "print(body" not in source
    assert "print(req" not in source


def test_secure_remote_e2e_includes_analysis_and_full_tool_discovery() -> None:
    source = _script_source()

    assert "'get_futures_runtime_health'" in source
    assert "'get_market_analysis'" in source
    assert "'get_cn_market_data'" in source
    assert "'get_cn_market_analysis'" in source
    assert "Call get_market_analysis exactly once for AMD" in source
    assert "Call get_cn_market_data exactly once" in source
    assert "Call get_cn_market_analysis exactly once" in source
    assert "len(names) != 7" in source
    assert "len(discovered) == 7" in source
    assert "len(names) != 5" not in source
    assert "len(names) != 3" not in source
