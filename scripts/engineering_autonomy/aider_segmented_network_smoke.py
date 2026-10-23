"""Segmented three-container Aider E2E: agent -> gateway -> FAKE provider.

Offline research only. No real provider keys, real model egress or trading.
Server roles use different Docker-internal bridges; the agent has no interface
on the fake-provider bridge. The gateway changes the outbound request.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from threading import Barrier, Lock
import urllib.error
import urllib.request

AGENT_KEY = "fake-agent-key-offline-only"
GATE_KEY = "fake-gateway-key-offline-only"
LIMIT = 256
MAX_BODY = 65536
MODEL = "gpt-4o-mini"
GATE_URL = "http://fake-gateway:8020"
UPSTREAM_URL = "http://fake-provider:8021/v1/chat/completions"


def fake_completion():
    return {
        "id": "chatcmpl-segmented-fake",
        "object": "chat.completion",
        "created": 1,
        "model": MODEL,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 2, "total_tokens": 32},
    }


def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def reply(handler, status: int, data: dict):
    body = json.dumps(data, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (OSError, ConnectionError):
        pass


def read_object(handler):
    length = handler.headers.get("Content-Length", "")
    if not length.isdecimal() or not 0 < int(length) <= MAX_BODY:
        return None
    try:
        raw = handler.rfile.read(int(length))
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (ValueError, UnicodeError):
        return None


def serve_provider(mode: str):
    counters = {"posts": 0, "max256": True, "fake_key": True, "non_stream": True}

    class FakeProvider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path == "/__state":
                reply(self, 200, counters)
            else:
                reply(self, 404, {})

        def do_POST(self):
            payload = read_object(self)
            if self.path != "/v1/chat/completions" or payload is None:
                reply(self, 400, {})
                return
            counters["posts"] += 1
            counters["max256"] = (counters["max256"] and
                                  type(payload.get("max_tokens")) is int and
                                  payload["max_tokens"] == LIMIT)
            counters["fake_key"] = (counters["fake_key"] and
                                    self.headers.get("Authorization") ==
                                    "Bearer " + GATE_KEY)
            counters["non_stream"] = counters["non_stream"] and payload.get("stream") is False
            if mode == "http503":
                reply(self, 503, {"error": {"message": "FAKE 503", "type": "server_error"}})
            else:
                reply(self, 200, fake_completion())

    print("SEGMENT_PROVIDER=READY", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8021), FakeProvider).serve_forever()


def serve_gateway():
    counters = {"inbound": 0, "admitted": 0, "denied": 0}
    reservation_lock = Lock()
    transport = opener()

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path != "/__state":
                reply(self, 404, {})
                return
            try:
                with transport.open("http://fake-provider:8021/__state", timeout=2) as response:
                    provider = json.loads(response.read(4096))
            except (urllib.error.URLError, ValueError, OSError):
                reply(self, 503, {"status": "provider-unavailable"})
                return
            with reservation_lock:
                snapshot = dict(counters)
            reply(self, 200, {"gateway": snapshot, "provider": provider})

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                counters["denied"] += 1
                reply(self, 400, {})
                return
            payload = read_object(self)
            # Exactly one thread may reserve the mock upstream quota.
            # Validation, admitted-count check and reservation share ONE lock.
            with reservation_lock:
                counters["inbound"] += 1
                if counters["admitted"] >= 1:
                    counters["denied"] += 1
                    reply(self, 429, {"error": {"message": "mock quota",
                                                 "type": "rate_limit_error"}})
                    return
                valid = (
                    payload is not None
                    and self.headers.get("Authorization") == "Bearer " + AGENT_KEY
                    and payload.get("model") == MODEL
                    and payload.get("stream") in (False, None)
                    and isinstance(payload.get("messages"), list)
                    and bool(payload["messages"])
                )
                if not valid:
                    counters["denied"] += 1
                    reply(self, 400, {})
                    return
                cap = payload.get("max_tokens")
                if cap is not None and (type(cap) is not int or not 0 < cap <= LIMIT):
                    counters["denied"] += 1
                    reply(self, 400, {})
                    return
                outbound = {
                    "model": MODEL,
                    "messages": payload["messages"],
                    "max_tokens": LIMIT if cap is None else cap,
                    "stream": False,
                }
                try:
                    raw = json.dumps(outbound, ensure_ascii=False).encode("utf-8")
                except UnicodeError:
                    counters["denied"] += 1
                    reply(self, 400, {})
                    return
                if len(raw) > MAX_BODY:
                    counters["denied"] += 1
                    reply(self, 413, {})
                    return
                # Reserve before *any* simulated provider network attempt.
                counters["admitted"] += 1
            req = urllib.request.Request(
                UPSTREAM_URL, data=raw,
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + GATE_KEY},
                method="POST",
            )
            try:
                with transport.open(req, timeout=4) as response:
                    output = response.read(32769)
                    if response.status != 200 or len(output) > 32768:
                        raise ValueError("bad fake response")
                parsed = json.loads(output)
                if not isinstance(parsed, dict):
                    raise ValueError("not a dict")
                reply(self, 200, parsed)
            except (urllib.error.HTTPError, urllib.error.URLError,
                    UnicodeError, ValueError, OSError, TimeoutError):
                reply(self, 503, {"error": {"message": "FAKE unavailable",
                                             "type": "server_error"}})

    print("SEGMENT_GATEWAY=READY", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8020), Gateway).serve_forever()


def check_namespace(provider_ip):
    # Container bridge is internal. No route to any public IPv4 destination.
    try:
        lines = open("/proc/net/route", encoding="ascii").read().splitlines()[1:]
        if any(len(parts := line.split()) > 1 and parts[1] == "00000000"
               for line in lines):
            return False, "unexpected-default-route"
    except OSError:
        return False, "cannot-read-route"

    try:
        socket.getaddrinfo("fake-provider", 8021)
        return False, "provider-hostname-resolvable"
    except socket.gaierror:
        pass

    try:
        with socket.create_connection((provider_ip, 8021), timeout=1.5):
            return False, "provider-address-directly-reachable"
    except OSError:
        pass

    return True, "no-provider-direct-route"


def client(mode, provider_ip):
    ok, reason = check_namespace(provider_ip)
    print(f"SEGMENT_NETWORK={reason}", flush=True)
    if not ok:
        return 2
    transport = opener()
    state_url = GATE_URL + "/__state"

    def state():
        with transport.open(state_url, timeout=2) as response:
            return json.loads(response.read(4096))

    for _ in range(40):
        try:
            state()
            break
        except (urllib.error.URLError, ValueError, OSError):
            time.sleep(0.1)
    else:
        print("SEGMENT_CLIENT=BLOCKED;REASON=GATEWAY_UNAVAILABLE")
        return 2

    if mode == "stress":
        workers = 12
        barrier = Barrier(workers)
        raw = json.dumps({
            "model": MODEL,
            "stream": False,
            "messages": [{"role": "user", "content": "simulated quota stress"}],
        }).encode("utf-8")
        def attempt(_):
            barrier.wait(timeout=10)
            req = urllib.request.Request(
                GATE_URL + "/v1/chat/completions", data=raw,
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + AGENT_KEY},
                method="POST",
            )
            try:
                with transport.open(req, timeout=6) as response:
                    response.read(2048)
                    return response.status
            except urllib.error.HTTPError as exc:
                return exc.code
            except (urllib.error.URLError, OSError, TimeoutError):
                return 0

        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(attempt, range(workers)))
        final = state()
        gate, provider = final["gateway"], final["provider"]
        good = (
            outcomes.count(200) == 1 and outcomes.count(429) == workers - 1
            and gate["inbound"] == workers
            and gate["admitted"] == 1
            and gate["denied"] == workers - 1
            and provider["posts"] == 1
            and provider["max256"] and provider["fake_key"] and provider["non_stream"]
        )
        print(
            f"SEGMENT_STRESS=TOTAL={workers};UPSTREAM={provider['posts']};"
            f"ALLOWED={gate['admitted']};DENIED={gate['denied']};"
            f"UPSTREAM_MAX_256={provider['max256']};"
            f"RESULT={'PASS' if good else 'FAIL'}", flush=True,
        )
        return 0 if good else 2

    with tempfile.TemporaryDirectory(prefix="aider-segmented-") as cwd:
        env = {
            "HOME": cwd,
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONPATH": "",
            "OPENAI_API_BASE": GATE_URL + "/v1",
            "OPENAI_BASE_URL": GATE_URL + "/v1",
            "OPENAI_API_KEY": AGENT_KEY,
            "LITELLM_MAX_RETRIES": "0",
            "AIDER_NO_ANALYTICS": "true",
            "AIDER_NO_CHECK_UPDATE": "true",
            "NO_PROXY": "fake-gateway,127.0.0.1,localhost",
        }
        cmd = [
            sys.executable, "-m", "aider", "--model", "openai/" + MODEL,
            "--no-git", "--no-stream", "--no-analytics",
            "--no-auto-commits", "--no-check-update",
            "--no-show-model-warnings", "--no-cache-prompts",
            "--no-pretty", "--timeout", "10",
            "--message", "Reply exactly OK, do not edit files",
            "--yes-always",
        ]
        with subprocess.Popen(
            cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            errors="replace",
        ) as process:
            deadline = time.monotonic() + 35
            last = None
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    last = state()
                except (urllib.error.URLError, OSError, ValueError):
                    pass
                if last and mode == "http503" and last["gateway"]["denied"] >= 1:
                    process.terminate()
                    break
                time.sleep(0.1)
            timeout = time.monotonic() >= deadline
            if process.poll() is None:
                process.terminate()
            try:
                process.communicate(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=4)
            exit_code = 124 if timeout else process.returncode

    final = state()
    gate, provider = final["gateway"], final["provider"]
    print(
        f"SEGMENT_MODE={mode};AGENT_POSTS={gate['inbound']};"
        f"GATE_ALLOWED={gate['admitted']};GATE_DENIED={gate['denied']};"
        f"FAKE_PROVIDER_POSTS={provider['posts']};"
        f"UPSTREAM_MAX_256={provider['max256']};"
        f"FAKE_UPSTREAM_KEY={provider['fake_key']};"
        f"NON_STREAM={provider['non_stream']};EXIT={exit_code}",
        flush=True,
    )
    shared = (gate["admitted"] == 1 and provider["posts"] == 1
              and provider["max256"] and provider["fake_key"]
              and provider["non_stream"])
    if mode == "success":
        good = shared and gate["inbound"] == 1 and gate["denied"] == 0 and exit_code == 0
    else:
        good = (shared and gate["inbound"] >= 2 and gate["denied"] >= 1
                and exit_code != 0)
    print("SEGMENT_TEST=" + ("PASS" if good else "FAIL"), flush=True)
    return 0 if good else 2


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="role", required=True)
    provider = sub.add_parser("provider")
    provider.add_argument("--mode", required=True, choices=("success", "http503"))
    sub.add_parser("gateway")
    agent = sub.add_parser("client")
    agent.add_argument("--mode", required=True, choices=("success", "http503", "stress"))
    agent.add_argument("--provider-ip", required=True)
    opts = parser.parse_args()
    if opts.role == "provider":
        serve_provider(opts.mode)
    elif opts.role == "gateway":
        serve_gateway()
    else:
        return client(opts.mode, opts.provider_ip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
