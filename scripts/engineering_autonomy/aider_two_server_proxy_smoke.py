"""Two-server fake-provider integration for actual pinned Aider in --network none.

Absolutely no real API key, external network route, provider forwarding, or
production admission. Gateway accepts dummy Aider credentials, enforces a
single *simulated* upstream attempt, injects a bounded max_tokens, and forwards
only to a second loopback fake server using a different dummy credential.

This is an experiment: tokenized input, upstream spending and production
egress are NOT proved safe by running it.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from threading import Event, Lock, Thread
import urllib.error
import urllib.request

AIDER_DUMMY_KEY = "dummy-aider-key-not-provider"
GATEWAY_DUMMY_KEY = "dummy-gateway-upstream-key-not-provider"
MAX_OUTPUT_PER_ATTEMPT = 256
MAX_BODY = 65536
MAX_RESPONSE = 32768
PROMPT = "Reply exactly OK. Do not edit files and do not call tools."
MODEL = "openai/gpt-4o-mini"


def fake_response() -> bytes:
    return json.dumps({
        "id": "chatcmpl-second-loopback-fake",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o-mini",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "OK"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 30, "completion_tokens": 2, "total_tokens": 32},
    }).encode("utf-8")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def start_http(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_http(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=4)


def network_none_verified() -> bool:
    try:
        interfaces = {x.name for x in Path("/sys/class/net").iterdir()}
        if interfaces != {"lo"}:
            return False
        route = Path("/proc/net/route")
        for line in route.read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) > 1 and parts[1] == "00000000" and parts[0] != "lo":
                return False
        return True
    except (OSError, ValueError):
        return False


def run_scenario(mode: str) -> dict[str, object]:
    if mode not in {"success", "upstream503"}:
        raise ValueError("unsupported mock mode")

    lock = Lock()
    stop_child = Event()
    inbound = []
    forwarded = []
    counters = {"gateway_denied": 0, "gateway_admitted": 0}

    class FakeProvider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            length = self.headers.get("Content-Length", "")
            if (self.path != "/v1/chat/completions" or not length.isdecimal()
                    or int(length) > MAX_BODY):
                self.send_error(400)
                return
            raw = self.rfile.read(int(length))
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeError):
                body = None
            record = {
                "max_tokens": body.get("max_tokens") if isinstance(body, dict) else None,
                "stream": body.get("stream") if isinstance(body, dict) else None,
                "model": body.get("model") if isinstance(body, dict) else None,
                "dummy_upstream_key": self.headers.get("Authorization")
                == "Bearer " + GATEWAY_DUMMY_KEY,
            }
            with lock:
                forwarded.append(record)
            if mode == "upstream503":
                self.send_error(503)
                return
            result = fake_response()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)

    fake, fake_thread = start_http(FakeProvider)
    fake_url = f"http://127.0.0.1:{fake.server_port}/v1/chat/completions"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    )

    class PolicyGateway(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            size = self.headers.get("Content-Length", "")
            valid_size = size.isdecimal() and 0 < int(size) <= MAX_BODY
            if self.path != "/v1/chat/completions" or not valid_size:
                stop_child.set()
                self.send_error(400)
                return
            raw = self.rfile.read(int(size))
            try:
                payload = json.loads(raw)
            except (UnicodeError, ValueError):
                payload = None
            # Evidence logs omit all prompt text and authorization values.
            record = {
                "original_max_tokens": payload.get("max_tokens")
                if isinstance(payload, dict) else None,
                "dummy_agent_key": self.headers.get("Authorization")
                == "Bearer " + AIDER_DUMMY_KEY,
            }
            with lock:
                inbound.append(record)
                if counters["gateway_admitted"] >= 1:
                    counters["gateway_denied"] += 1
                    stop_child.set()
                    self.send_error(429)
                    return

                if (not record["dummy_agent_key"] or not isinstance(payload, dict)
                        or payload.get("model") != "gpt-4o-mini"
                        or payload.get("stream") not in (None, False)
                        or not isinstance(payload.get("messages"), list)
                        or not payload["messages"]):
                    counters["gateway_denied"] += 1
                    stop_child.set()
                    self.send_error(400)
                    return

                incoming_limit = payload.get("max_tokens")
                if incoming_limit is not None and (
                    type(incoming_limit) is not int or incoming_limit <= 0
                    or incoming_limit > MAX_OUTPUT_PER_ATTEMPT
                ):
                    counters["gateway_denied"] += 1
                    stop_child.set()
                    self.send_error(400)
                    return
                # Use only allowlisted fields; do not forward unreviewed
                # provider override options or model aliases.
                bounded = {
                    "model": "gpt-4o-mini",
                    "messages": payload["messages"],
                    "max_tokens": MAX_OUTPUT_PER_ATTEMPT if incoming_limit is None
                    else incoming_limit,
                    "stream": False,
                }
                wire = json.dumps(
                    bounded, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                if len(wire) > MAX_BODY:
                    counters["gateway_denied"] += 1
                    stop_child.set()
                    self.send_error(413)
                    return
                # Claim BEFORE touching mock upstream. Never refund or retry.
                counters["gateway_admitted"] += 1
            request = urllib.request.Request(
                fake_url, data=wire, method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + GATEWAY_DUMMY_KEY,
                },
            )
            try:
                with opener.open(request, timeout=4) as resp:
                    body = resp.read(MAX_RESPONSE + 1)
                    if resp.status != 200 or len(body) > MAX_RESPONSE:
                        raise ValueError("mock response refused")
            except (urllib.error.HTTPError, urllib.error.URLError,
                    TimeoutError, OSError, ValueError):
                # Failure is deliberately passed back as 503 to test real
                # Aider/LiteLLM retries. Second attempt is blocked above.
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    gateway, gateway_thread = start_http(PolicyGateway)
    try:
        with tempfile.TemporaryDirectory(prefix="sr-aider-two-server-") as work:
            env = {
                "HOME": work,
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PYTHONPATH": "",
                "OPENAI_API_BASE": f"http://127.0.0.1:{gateway.server_port}/v1",
                "OPENAI_BASE_URL": f"http://127.0.0.1:{gateway.server_port}/v1",
                "OPENAI_API_KEY": AIDER_DUMMY_KEY,
                "LITELLM_MAX_RETRIES": "0",
                "AIDER_NO_CHECK_UPDATE": "true",
                "AIDER_NO_ANALYTICS": "true",
                "NO_PROXY": "localhost,127.0.0.1",
            }
            cmd = [
                sys.executable, "-m", "aider", "--model", MODEL,
                "--no-stream", "--no-git", "--no-analytics",
                "--no-auto-commits", "--no-check-update",
                "--no-show-model-warnings", "--no-cache-prompts",
                "--no-pretty", "--timeout", "10", "--message", PROMPT,
                "--yes-always",
            ]
            with subprocess.Popen(
                cmd, cwd=work, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, errors="replace",
            ) as process:
                deadline = time.monotonic() + 35
                while (process.poll() is None and
                       not stop_child.is_set() and time.monotonic() < deadline):
                    time.sleep(0.08)
                timed_out = time.monotonic() >= deadline
                stopped_by_gate = stop_child.is_set()
                if process.poll() is None:
                    process.terminate()
                try:
                    process.communicate(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=4)
                exit_code = 124 if timed_out else process.returncode
    finally:
        stop_http(gateway, gateway_thread)
        stop_http(fake, fake_thread)

    return {
        "mode": mode,
        "exit_code": exit_code,
        "stopped_by_gate": stopped_by_gate,
        "inbound": inbound,
        "forwarded": forwarded,
        "counters": counters,
    }


def main() -> int:
    if (os.environ.get("STOCK_RAZOR_NETWORK_NONE") != "verified-by-runner"
            or not network_none_verified()):
        print("AIDER_TWO_SERVER=BLOCKED;REASON=NO_NETWORK_NONE_EVIDENCE")
        return 2
    failures = []
    for mode in ("success", "upstream503"):
        result = run_scenario(mode)
        inbound = result["inbound"]
        forwarded = result["forwarded"]
        gate = result["counters"]
        upstream_bounded = all(
            x["max_tokens"] == MAX_OUTPUT_PER_ATTEMPT
            and x["stream"] is False
            and x["model"] == "gpt-4o-mini"
            and x["dummy_upstream_key"] for x in forwarded
        )
        print(
            f"AIDER_TWO_SERVER_MODE={mode};INBOUND={len(inbound)};"
            f"FAKE_UPSTREAM_POSTS={len(forwarded)};"
            f"GATE_ADMITTED={gate['gateway_admitted']};"
            f"GATE_DENIED={gate['gateway_denied']};"
            f"UPSTREAM_MAX_TOKENS_256={upstream_bounded};"
            f"EXIT={result['exit_code']}"
        )
        if (len(forwarded) != 1 or gate["gateway_admitted"] != 1
                or not upstream_bounded or
                not all(x["dummy_agent_key"] for x in inbound)):
            failures.append(mode + ":wrong_mock_forward_or_key")
        if mode == "success":
            if result["exit_code"] != 0 or len(inbound) != 1:
                failures.append("success:client_not_completed")
        else:
            if (result["exit_code"] == 0 or
                    len(inbound) < 2 or gate["gateway_denied"] < 1 or
                    not result["stopped_by_gate"]):
                failures.append("upstream503:retry_not_blocked")
    if failures:
        print("AIDER_TWO_SERVER=FAIL;REASONS=" + ",".join(failures))
        return 2
    print("AIDER_TWO_SERVER=OFFLINE_GATEWAY_INJECTION_PASS;PAID_CODING=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
