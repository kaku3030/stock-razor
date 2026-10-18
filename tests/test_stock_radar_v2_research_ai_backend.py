"""Real SDK through offline HTTP transport; actual killable child, no model I/O."""
import io
import json
import subprocess
import sys
import time
from datetime import timedelta

import httpx
import pytest

from src.llm.generation_backend import GenerationError, GenerationErrorCode
from src.services.stock_radar_v2 import research_ai_backend as module
from tests.test_stock_radar_v2_ai_event_consumer import NOW, SHA, consumer, event
from src.services.stock_radar_v2.bar_event_ledger import RadarBarEventLedger


def payload(**changes):
    data = dict(provider="openai", model="offline-model", api_key="offline-private-key",
                prompt='{"event_id":"offline"}', system_prompt="Research JSON only.",
                timeout=1, max_output_tokens=128, request_id="a" * 64)
    data.update(changes)
    return data


def response_body(**changes):
    data = {"choices": [{"finish_reason": "stop", "message": {"content": '{"assessment":"WATCH"}'}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}}
    data.update(changes)
    return data


def backend(**changes):
    data = dict(provider="openai", model="offline-model", api_key="offline-private-key", enabled=True)
    data.update(changes)
    return module.ResearchAIRequestBackend(**data)


def generate(b=None, **kwargs):
    return (b or backend()).generate('facts', {"timeout": 1, "max_output_tokens": 128},
                                    system_prompt="Research JSON only.",
                                    audit_context={"request_id": "a" * 64}, **kwargs)


@pytest.mark.parametrize("provider,host,token_field", [
    ("openai", "api.openai.com", "max_completion_tokens"),
    ("deepseek", "api.deepseek.com", "max_tokens"),
])
def test_actual_sdk_sends_one_bounded_nonstream_request(provider, host, token_field):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response_body())
    result = module._request_once(payload(provider=provider), transport=httpx.MockTransport(handle))
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST" and request.url.host == host
    assert request.url.path.endswith("/chat/completions")
    body = json.loads(request.content)
    assert body[token_field] == 128 and body["stream"] is False
    assert set(body) == {"messages", "model", "stream", token_field}
    assert request.headers["X-Client-Request-Id"] == "a" * 64
    assert result["usage"]["total_tokens"] == 30
    assert set(result) == {"text", "usage"}


@pytest.mark.parametrize("failure", [401, 408, 409, 429, 500, 503, "connection", "timeout", 307])
def test_actual_sdk_does_not_retry_or_follow_redirects(failure):
    requests = []
    def handle(request):
        requests.append(request)
        if failure == "connection":
            raise httpx.ConnectError("private-provider-detail", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-provider-detail", request=request)
        return httpx.Response(failure, headers={"location": "https://untrusted.invalid"},
                              json={"error": {"message": "private-provider-detail"}})
    with pytest.raises(Exception):
        module._request_once(payload(), transport=httpx.MockTransport(handle))
    assert len(requests) == 1


@pytest.mark.parametrize("changes", [
    {"provider": "untrusted"}, {"model": "private\nmodel"}, {"api_key": "key\nsecret"},
    {"timeout": True}, {"timeout": 61}, {"max_output_tokens": 2049},
    {"request_id": "bad-header\nsecret"}, {"prompt": "x" * 16385}, {"system_prompt": "x" * 4097},
])
def test_invalid_inputs_block_before_transport(changes):
    requests = []
    with pytest.raises(ValueError):
        module._request_once(payload(**changes), transport=httpx.MockTransport(lambda r: requests.append(r)))
    assert requests == []


@pytest.mark.parametrize("body", [
    response_body(usage=None),
    response_body(usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 31}),
    response_body(usage={"prompt_tokens": True, "completion_tokens": 10, "total_tokens": 11}),
    response_body(usage={"prompt_tokens": 20, "completion_tokens": 129, "total_tokens": 149}),
    response_body(choices=[{"finish_reason": "length", "message": {"content": "truncated"}}]),
    response_body(choices=[{"finish_reason": "stop", "message": {"content": "x" * 16385}}]),
    response_body(choices=[{"finish_reason": "stop", "message": {"content": "x", "tool_calls": ["tool"]}}]),
    response_body(extra="x" * 65536),
])
def test_sdk_response_bytes_tokens_and_completion_are_verified(body):
    with pytest.raises(ValueError):
        module._request_once(payload(), transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))


def test_no_ambient_proxy_or_debug_configuration(monkeypatch):
    observed = []
    real_client = httpx.Client
    class Client(real_client):
        def __init__(self, *args, **kwargs):
            observed.append(kwargs)
            super().__init__(*args, **kwargs)
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted.invalid")
    monkeypatch.setattr(httpx, "Client", Client)
    module._request_once(payload(), transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response_body())))
    assert observed[0]["trust_env"] is False
    assert observed[0]["follow_redirects"] is False


def test_disabled_backend_does_not_spawn(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected child"))
    with pytest.raises(GenerationError) as error:
        generate(backend(enabled=False))
    assert error.value.error_code == GenerationErrorCode.BACKEND_NOT_CONFIGURED
    assert "offline-private-key" not in repr(backend())


def test_actual_stuck_child_is_killed_at_deadline(monkeypatch):
    real_popen, processes = subprocess.Popen, []
    def hanging_child(args, **kwargs):
        assert args == [sys.executable, "-E", "-X", "utf8", "-m", module._MODULE]
        assert "offline-private-key" not in repr(args)
        child = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        processes.append(child)
        return child
    monkeypatch.setattr(subprocess, "Popen", hanging_child)
    started = time.monotonic()
    with pytest.raises(GenerationError) as error:
        generate()
    assert error.value.error_code == GenerationErrorCode.TIMEOUT
    assert time.monotonic() - started < 5
    assert len(processes) == 1 and processes[0].poll() is not None
    assert error.value.retryable is False and error.value.fallbackable is False


def test_real_worker_invalid_input_emits_no_secret_or_traceback():
    result = subprocess.run([sys.executable, "-E", "-X", "utf8", "-m", module._MODULE],
        input=json.dumps(payload(provider="invalid")).encode(), capture_output=True, timeout=5)
    assert result.returncode == 1 and result.stdout == b"" and result.stderr == b""


class OfflineChild:
    def __init__(self, handle, capture, **kwargs):
        self.handle, self.capture = handle, capture
        self.stdin, self.stdout, self.returncode = io.BytesIO(), io.BytesIO(), 0
        capture.append(kwargs)

    def communicate(self, wire, timeout):
        self.capture[-1]["payload"] = json.loads(wire)
        try:
            result = module._request_once(json.loads(wire), transport=httpx.MockTransport(self.handle))
            return json.dumps(result).encode(), None
        except Exception:
            self.returncode = 1
            return b"", None

    def poll(self):
        return self.returncode


@pytest.mark.parametrize("fail", [False, True])
def test_consumer_sdk_receipt_reopen_and_uncertain_barrier(tmp_path, monkeypatch, fail):
    requests, captures, clock = [], [], [NOW]
    def handle(request):
        requests.append(request)
        if fail:
            return httpx.Response(500, json={"error": {"message": "offline-private-key"}})
        facts = json.loads(json.loads(request.content)["messages"][1]["content"])
        body = response_body()
        body["choices"][0]["message"]["content"] = json.dumps({
            "event_id": facts["event_id"], "assessment": "WATCH", "evidence_fields": ["close"]})
        return httpx.Response(200, json=body)
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-secret")
    monkeypatch.setenv("OPENAI_LOG", "debug")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: OfflineChild(handle, captures, **k))
    path = tmp_path / "ledger.sqlite"
    with RadarBarEventLedger(path) as ledger:
        saved = ledger.record(event(), recorded_at=NOW)
        if not fail:
            ledger.acknowledge = lambda *a, **k: (_ for _ in ()).throw(PermissionError("offline ACK fault"))
        result = consumer(ledger, backend(), clock).poll_once()
        assert result.status == ("UNKNOWN" if fail else "ACK_PENDING")
        assert ledger.get_ai_wake(saved.event.idempotency_key, now=NOW).status == ("UNKNOWN" if fail else "SUCCEEDED")
    clock[0] += timedelta(seconds=200)
    with RadarBarEventLedger(path) as ledger:
        result = consumer(ledger, backend(), clock).poll_once()
        assert result.status == ("UNKNOWN" if fail else "RECOVERED")
    assert len(requests) == len(captures) == 1
    assert "OPENAI_API_KEY" not in captures[0]["env"] and "OPENAI_LOG" not in captures[0]["env"]
    assert captures[0]["stderr"] == subprocess.DEVNULL
    assert b"offline-private-key" not in path.read_bytes()
    assert b"ambient-secret" not in path.read_bytes()


@pytest.mark.parametrize("config", [
    {"timeout": 0, "max_output_tokens": 128},
    {"timeout": 1, "max_output_tokens": 128, "retries": 1},
    {"timeout": 1, "max_output_tokens": 128, "base_url": "https://untrusted.invalid"},
])
def test_backend_rejects_extra_or_unsafe_execution_config(monkeypatch, config):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected child"))
    with pytest.raises(GenerationError) as error:
        backend().generate("facts", config, system_prompt="Research JSON.", audit_context={"request_id": "a" * 64})
    assert error.value.retryable is False and error.value.fallbackable is False


def test_stream_and_ambient_request_identity_are_rejected(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected child"))
    with pytest.raises(GenerationError):
        generate(stream=True)
    with pytest.raises(GenerationError):
        backend().generate("facts", {"timeout": 1, "max_output_tokens": 128}, system_prompt="Research JSON.")
