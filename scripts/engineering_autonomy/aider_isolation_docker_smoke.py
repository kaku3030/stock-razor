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
from threading import Thread

DUMMY_KEY = "stock-razor-offline-dummy-not-real"
MODEL = "openai/gpt-4o-mini"
PROMPT = "Reply exactly OK. Do not edit files, do not call tools."
MAX_BODY = 1_000_000


def run_scenario(mode: str) -> dict[str, object]:
    requests: list[dict[str, object]] = []

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
            requests.append({
                "path": self.path,
                "model": payload.get("model") if isinstance(payload, dict) else None,
                "stream": payload.get("stream") if isinstance(payload, dict) else None,
                "max_tokens": payload.get("max_tokens") if isinstance(payload, dict) else None,
                "fake_key_only": self.headers.get("Authorization") == f"Bearer {DUMMY_KEY}",
            })
            if mode == "http503":
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
            try:
                proc = subprocess.run(
                    cmd, cwd=work, env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, errors="replace", timeout=65, check=False,
                )
                status = proc.returncode
            except subprocess.TimeoutExpired:
                status = 124
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=4)
    return {"mode": mode, "exit_code": status, "requests": requests}


def main() -> int:
    # Runner must prove Docker isolation externally; this code's local-only
    # host validation cannot enforce network egress limits for arbitrary Aider.
    if os.environ.get("STOCK_RAZOR_NETWORK_NONE") != "verified-by-runner":
        print("AIDER_ISOLATION=BLOCKED;REASON=NO_NETWORK_NAMESPACE_EVIDENCE")
        return 2
    failures = []
    for mode in ("success", "http503"):
        result = run_scenario(mode)
        seen = result["requests"]
        count = len(seen)
        print(f"AIDER_LOOPBACK_MODE={mode};REQUESTS={count};EXIT={result['exit_code']}")
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
        if count != 1:
            failures.append(f"{mode}:expected-exactly-one-request")
        if mode == "success" and result["exit_code"] != 0:
            failures.append("success:aider-did-not-complete")
        if mode == "http503" and result["exit_code"] == 0:
            failures.append("http503:aider-ignored-provider-failure")
    if failures:
        print("AIDER_ISOLATION=FAILED;REASONS=" + ",".join(failures))
        return 2
    print("AIDER_ISOLATION=LOCALHOST_ONLY_PASS;PAID_CODING=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
