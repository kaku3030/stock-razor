"""Real localhost HTTP E2E, without DeepSeek API, network proxy, or bill."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Barrier, Thread

import pytest

from engineering_autonomy.deepseek_loopback_mock import (
    LoopbackDenied, LoopbackMockTransport,
)
from engineering_autonomy.deepseek_request_plan import MODEL, OfflineRequestPlan


@contextmanager
def fake_deepseek(*, status=200, body=None, redirect=None):
    observations = []
    if body is None:
        body = {
            "id": "local-test-only",
            "usage": {"prompt_tokens": 5, "completion_tokens": 12},
            "choices": [{"message": {"role": "assistant", "content": "mock"}}],
        }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "-1"))
            raw = self.rfile.read(max(0, length))
            observations.append({
                "path": self.path,
                "bytes": raw,
                "authorization": self.headers.get("Authorization"),
            })
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if redirect:
                self.send_header("Location", redirect)
            self.end_headers()
            serialized = (
                body if isinstance(body, bytes)
                else json.dumps(body).encode("utf-8")
            )
            try:
                self.wfile.write(serialized)
            except (ConnectionError, OSError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1/chat/completions", observations
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=4)


def new_request(plan, content="first"):
    return plan.reserve(
        model=MODEL,
        messages=[{"role": "user", "content": content}],
        claimed_input_tokens=100,
        max_tokens=150,
    )


def test_actual_local_http_receives_exact_checked_bytes_and_no_real_credential():
    plan = OfflineRequestPlan()
    sealed = new_request(plan)
    with fake_deepseek() as (endpoint, observed):
        result = LoopbackMockTransport(plan=plan, endpoint=endpoint).send_once(sealed)
    assert result == {
        "status": "SIMULATED_LOOPBACK_ONLY",
        "claimed_input_tokens": 100,
        "input_tokens_simulated": 5,
        "reserved_output_tokens": 150,
        "output_tokens_simulated": 12,
    }
    assert len(observed) == 1
    assert observed[0]["bytes"] == sealed
    assert observed[0]["path"] == "/v1/chat/completions"
    assert observed[0]["authorization"] == "Bearer offline-placeholder-not-real"
    assert json.loads(observed[0]["bytes"])["max_tokens"] == 150


@pytest.mark.parametrize("url", [
    "https://api.deepseek.com/v1/chat/completions",
    "http://localhost:8181/v1/chat/completions",
    "http://127.0.0.2:8181/v1/chat/completions",
    "http://[::1]:8181/v1/chat/completions",
    "https://127.0.0.1:8181/v1/chat/completions",
    "http://127.0.0.1:8181/other",
    "http://127.0.0.1:8181/v1/chat/completions?redirect=true",
    "http://user:password@127.0.0.1:8181/v1/chat/completions",
    "http://127.0.0.1:8181/v1/chat/completions#frag",
    "http://127.0.0.1:not-a-port/v1/chat/completions",
    "http://127.0.0.1:65536/v1/chat/completions",
    "http://127.0.0.1/v1/chat/completions",
    "http://127.0.0.1:8181@evil.invalid/v1/chat/completions",
])
def test_only_literal_localhost_ipv4_origin_is_accepted(url):
    with pytest.raises(LoopbackDenied, match="invalid mock destination"):
        LoopbackMockTransport(plan=OfflineRequestPlan(), endpoint=url)


def test_modified_payload_cannot_be_sent_and_does_not_spend_dispatch_claim():
    plan = OfflineRequestPlan()
    sealed = new_request(plan)
    modified = json.loads(sealed)
    modified["max_tokens"] = 30000
    forged = json.dumps(modified).encode("utf-8")
    with fake_deepseek() as (endpoint, observed):
        transport = LoopbackMockTransport(plan=plan, endpoint=endpoint)
        with pytest.raises(LoopbackDenied, match="bytes were not admitted"):
            transport.send_once(forged)
        transport.send_once(sealed)
    assert len(observed) == 1


def test_no_replay_even_when_local_server_returns_success():
    plan = OfflineRequestPlan()
    sealed = new_request(plan)
    with fake_deepseek() as (endpoint, observed):
        transport = LoopbackMockTransport(plan=plan, endpoint=endpoint)
        transport.send_once(sealed)
        with pytest.raises(LoopbackDenied, match="dispatch replay denied"):
            transport.send_once(sealed)
    assert len(observed) == 1


def test_parallel_transport_attempts_send_same_envelope_at_most_once():
    plan = OfflineRequestPlan()
    sealed = new_request(plan)
    with fake_deepseek() as (endpoint, observed):
        transport = LoopbackMockTransport(plan=plan, endpoint=endpoint)
        barrier = Barrier(6)

        def dispatch(_):
            barrier.wait(timeout=12)
            try:
                transport.send_once(sealed)
                return True
            except LoopbackDenied:
                return False

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(dispatch, range(6)))
    assert sum(results) == 1
    assert len(observed) == 1


def test_two_independent_requests_use_only_the_two_reserved_slots():
    plan = OfflineRequestPlan()
    one = new_request(plan, "one")
    two = new_request(plan, "two")
    with fake_deepseek() as (endpoint, observed):
        transport = LoopbackMockTransport(plan=plan, endpoint=endpoint)
        assert transport.send_once(one)["status"] == "SIMULATED_LOOPBACK_ONLY"
        assert transport.send_once(two)["status"] == "SIMULATED_LOOPBACK_ONLY"
    assert [json.loads(x["bytes"])["messages"][0]["content"] for x in observed] == [
        "one", "two",
    ]


def test_redirect_is_rejected_and_never_followed():
    plan = OfflineRequestPlan()
    sealed = new_request(plan)
    with fake_deepseek(
        status=302, redirect="https://api.deepseek.com/v1/chat/completions"
    ) as (endpoint, observed):
        with pytest.raises(LoopbackDenied, match="mock HTTP or response failure"):
            LoopbackMockTransport(plan=plan, endpoint=endpoint).send_once(sealed)
    assert len(observed) == 1


@pytest.mark.parametrize("body", [
    b"not json",
    b"Z" * 20000,
    {"usage": {"prompt_tokens": 101, "completion_tokens": 1}},
    {"usage": {"prompt_tokens": 10, "completion_tokens": 151}},
    {"usage": {"prompt_tokens": True, "completion_tokens": 1}},
    {"usage": {"prompt_tokens": 1, "completion_tokens": -1}},
    {"choices": [{"message": {"content": "no usage"}}]},
])
def test_mock_invalid_response_fails_closed_without_retry(body):
    plan = OfflineRequestPlan()
    sealed = new_request(plan)
    with fake_deepseek(body=body) as (endpoint, observed):
        transport = LoopbackMockTransport(plan=plan, endpoint=endpoint)
        with pytest.raises(LoopbackDenied):
            transport.send_once(sealed)
        with pytest.raises(LoopbackDenied, match="dispatch replay denied"):
            transport.send_once(sealed)
    assert len(observed) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_mock_upstream_failure_never_auto_retries(status):
    plan = OfflineRequestPlan()
    sealed = new_request(plan)
    with fake_deepseek(status=status) as (endpoint, observed):
        transport = LoopbackMockTransport(plan=plan, endpoint=endpoint)
        with pytest.raises(LoopbackDenied, match="mock HTTP or response failure"):
            transport.send_once(sealed)
        with pytest.raises(LoopbackDenied, match="dispatch replay denied"):
            transport.send_once(sealed)
    assert len(observed) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_mock_http_redirect_never_followed_even_when_post_replay_is_allowed(status):
    plan = OfflineRequestPlan()
    sealed = new_request(plan)
    with fake_deepseek(
        status=status, redirect="https://api.deepseek.com/v1/chat/completions"
    ) as (endpoint, observed):
        with pytest.raises(LoopbackDenied, match="mock HTTP or response failure"):
            LoopbackMockTransport(plan=plan, endpoint=endpoint).send_once(sealed)
    assert len(observed) == 1


def test_inherited_provider_secret_and_http_proxy_are_never_used(monkeypatch):
    secret = "DO_NOT_EXPOSE_THIS_PROVIDER_KEY"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    plan = OfflineRequestPlan()
    sealed = new_request(plan)
    with fake_deepseek() as (endpoint, observed):
        result = LoopbackMockTransport(plan=plan, endpoint=endpoint).send_once(sealed)
    assert result["status"] == "SIMULATED_LOOPBACK_ONLY"
    assert len(observed) == 1
    assert secret not in observed[0]["authorization"]
    assert secret.encode("utf-8") not in observed[0]["bytes"]
    assert observed[0]["authorization"] == "Bearer offline-placeholder-not-real"
