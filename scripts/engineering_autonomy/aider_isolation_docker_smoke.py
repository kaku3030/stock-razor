"""Prove pinned Aider calls localhost mock only, inside a --network none container.

Test harness only. This file must never receive real provider keys or secrets.
The enclosing GitHub Actions workflow builds dependencies first, then launches
this script in Docker with no network interface other than container loopback.
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

DUMMY_KEY = "stock-razor-offline-dummy-not-real"
MODEL = "openai/gpt-4o-mini"
PROMPT = "Reply exactly OK. Do not edit files, do not call tools."
MAX_BODY = 1_000_000


def run_scenario(mode: str) -> dict[str, object]:
    requests: list[dict[str, object]] = []
    state = {"accepted": 0, "denied": 0}
    locked = Lock()
    stop_on_policy_violation = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length_header = self.headers.get("Content-Length", "")
            if not length_header.isdigit() or int(length_header) > MAX_BODY:
                self.send_error(413)
                return
            raw = self.rfile.read(int(length_header))
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                payload = None
            record = {
                "path": self.path,
                "model": payload.get("model") if isinstance(payload, dict) else None,
                "stream": payload.get("stream") if isinstance(payload, dict) else None,
                "max_tokens": payload.get("max_tokens") if isinstance(payload, dict) else None,
                "fake_key_only": self.headers.get("Authorization") == f"Bearer {DUMMY_KEY}",
            }
            with locked:
                requests.append(record)
                if mode == "strict-gate":
                    # A real provider request must include a bounded max_tokens.
                    # The currently pinned Aider omits it: 100% reject, 0 upstream.
                    valid = (
                        record["fake_key_only"]
                        and record["path"] == "/v1/chat/completions"
                        and record["stream"] in (None, False)
                        and type(record["max_tokens"]) is int
                        and 0 < record["max_tokens"] <= 4000
                    )
                    if not valid:
                        state["denied"] += 1
                        stop_on_policy_violation.set()
                        self.send_error(400)
                        return
                if mode == "retry-budget-gate" and state["accepted"] >= 1:
                    state["denied"] += 1
                    stop_on_policy_violation.set()
                    self.send_error(429)
                    return
                state["accepted"] += 1
            if mode == "retry-budget-gate":
                # First fake upstream 503; no further call can pass this gate.
                self.send_error(503)
                return
            body = json.dumps({
                "id": "chatcmpl-local-only",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-4o-mini",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "OK"},
                     "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 40, "completion_tokens": 2, "total_tokens": 42},
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="sr-aider-offline-") as work:
            base_url = f"http://127.0.0.1:{server.server_port}/v1"
            # Explicit minimal subprocess environment: no GitHub, AWS, OpenAI or
            # DeepSeek host credentials can be inherited from the runner.
            env = {
                "HOME": work,
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "PYTHONPATH": "",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "OPENAI_API_BASE": base_url,
                "OPENAI_BASE_URL": base_url,
                "OPENAI_API_KEY": DUMMY_KEY,
                "LITELLM_MAX_RETRIES": "0",
                "AIDER_NO_CHECK_UPDATE": "true",
                "AIDER_NO_ANALYTICS": "true",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "NO_PROXY": "127.0.0.1,localhost",
            }
            cmd = [
                sys.executable, "-m", "aider",
                "--model", MODEL,
                "--no-stream",
                "--no-git",
                "--no-analytics",
                "--no-auto-commits",
                "--no-check-update",
                "--no-show-model-warnings",
                "--no-cache-prompts",
                "--no-pretty",
                "--timeout", "10",
                "--message", PROMPT,
                "--yes-always",
            ]
            # Stop the process promptly at the FIRST gateway policy breach;
            # do not wait for Aider to exhaust an unknown SDK retry schedule.
            with subprocess.Popen(
                cmd, cwd=work, env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, errors="replace",
            ) as proc:
                deadline = time.monotonic() + 35
                while (
                    proc.poll() is None
                    and not stop_on_policy_violation.is_set()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.08)
                stopped_by_gate = stop_on_policy_violation.is_set()
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.communicate(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate(timeout=4)
                status = proc.returncode if not (
                    proc.returncode is not None and time.monotonic() >= deadline
                ) else 124
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=4)
    return {
        "mode": mode, "exit_code": status, "requests": requests,
        "accepted": state["accepted"], "denied": state["denied"],
        "stopped_by_gate": stopped_by_gate,
    }


def verify_no_default_routes() -> bool:
    """The Docker test namespace must expose loopback and NO other interface.

    /proc/net/ipv6_route is absent when IPv6 is disabled, so requiring that
    file would falsely reject a correctly isolated container. Conversely a
    host-network container exposes ethernet interfaces and is always denied.
    """
    interfaces = Path("/sys/class/net")
    try:
        names = {entry.name for entry in interfaces.iterdir()}
    except OSError:
        print("AIDER_NETNS=INTERFACES_UNREADABLE")
        return False
    print("AIDER_NETNS=ONLY_LOOPBACK" if names == {"lo"} else
          "AIDER_NETNS=NON_LOOPBACK_INTERFACE_OR_NO_LOOPBACK")
    if names != {"lo"}:
        return False
    # A default route through a non-loopback device would be prohibited.
    try:
        ipv4 = Path("/proc/net/route")
        if ipv4.is_file():
            for line in ipv4.read_text().splitlines()[1:]:
                parts = line.split()
                if len(parts) > 1 and parts[1] == "00000000" and parts[0] != "lo":
                    return False
        ipv6 = Path("/proc/net/ipv6_route")
        if ipv6.is_file():
            for line in ipv6.read_text().splitlines():
                parts = line.split()
                if len(parts) >= 10 and parts[:2] == ["0" * 32, "00"] and parts[-1] != "lo":
                    return False
    except (OSError, ValueError):
        return False
    return True


def main() -> int:
    if (os.environ.get("STOCK_RAZOR_NETWORK_NONE") != "verified-by-runner"
            or not verify_no_default_routes()):
        print("AIDER_ISOLATION=BLOCKED;REASON=NO_NETWORK_NAMESPACE_EVIDENCE")
        return 2

    failures = []
    for mode in ("success", "strict-gate", "retry-budget-gate"):
        result = run_scenario(mode)
        seen = result["requests"]
        count = len(seen)
        accepted = result["accepted"]
        denied = result["denied"]
        print(
            f"AIDER_LOOPBACK_MODE={mode};REQUESTS={count};"
            f"ACCEPTED_MOCK_UPSTREAM={accepted};DENIED_AT_GATE={denied};"
            f"EXIT={result['exit_code']}"
        )
        if count:
            first = seen[0]
            print(
                "AIDER_LOOPBACK_FIRST="
                f"PATH_OK={first['path'] == '/v1/chat/completions'};"
                f"FAKE_KEY_ONLY={first['fake_key_only']};"
                f"NON_STREAM={first['stream'] in (False, None)};"
                f"MAX_TOKENS_PRESENT={type(first['max_tokens']) is int}"
            )
            if not first["fake_key_only"] or first["path"] != "/v1/chat/completions":
                failures.append(f"{mode}:wrong-endpoint-or-credential")
        if mode == "success":
            if count != 1 or accepted != 1 or result["exit_code"] != 0:
                failures.append("success:real-aider-localhost-smoke")
        elif mode == "strict-gate":
            # Any unbounded call must be refused before forwarding.
            if accepted != 0 or denied < 1 or count < 1:
                failures.append("strict-gate:unbounded-model-request-forwarded")
        elif mode == "retry-budget-gate":
            # Aider may try hidden retries. The gate may forward ONLY the
            # first fake 503 to its mock; all additional attempts are blocked.
            if accepted != 1 or count < 1 or result["exit_code"] == 0:
                failures.append("retry-budget-gate:provider-attempt-control-failed")
            print(f"AIDER_INTERNAL_RETRY_OBSERVED={count > 1}")
    if failures:
        print("AIDER_ISOLATION=FAILED;REASONS=" + ",".join(failures))
        return 2
    print("AIDER_ISOLATION=GATE_FAIL_CLOSED_LOOPBACK_PASS;PAID_CODING=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
