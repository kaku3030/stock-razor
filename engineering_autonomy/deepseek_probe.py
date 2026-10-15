"""One-request, secret-safe DeepSeek HTTP reachability and response-shape probe.

Never log API keys, response bodies, request IDs or other upstream content.
This is independent from Aider and LiteLLM and never modifies repository files.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

ENDPOINT = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
MAX_RESPONSE_BYTES = 65_536
REQUEST = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "Reply with OK."}],
    "thinking": {"type": "disabled"},
    "max_tokens": 24,
    "stream": False,
}


def validate_completion(body: bytes) -> None:
    """Only test structural fields; never return or log completion contents."""
    if not body or len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("unexpected_response_size")
    try:
        obj = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("id"), str) or not obj["id"]:
        raise ValueError("missing_id")
    choices = obj.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("missing_choices")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str) or not message["content"].strip():
        raise ValueError("missing_content")


def classify_status(status: int) -> str:
    if status in (401, 403):
        return "AUTH"
    if status == 402:
        return "BILLING"
    if status == 429:
        return "RATE_LIMIT"
    if status in (400, 404, 422):
        return "REQUEST_OR_MODEL"
    if status >= 500:
        return "UPSTREAM"
    return "HTTP_OTHER"


def main() -> int:
    start = time.monotonic()
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        print("DEEPSEEK_PROBE=BLOCKED;CATEGORY=MISSING_KEY;HTTP_STATUS=NA;MODEL=" + MODEL)
        return 2
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(REQUEST, separators=(",", ":")).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    category, status, passed = "UNKNOWN", "NA", False
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = str(response.status)
            if response.status != 200:
                category = classify_status(response.status)
            else:
                validate_completion(response.read(MAX_RESPONSE_BYTES + 1))
                category, passed = "VALID_COMPLETION", True
    except urllib.error.HTTPError as exc:
        status, category = str(exc.code), classify_status(exc.code)
        # Deliberately never read or print upstream error response bodies.
    except (urllib.error.URLError, TimeoutError, OSError):
        category = "NETWORK_OR_TIMEOUT"
    except ValueError:
        category = "INVALID_RESPONSE_SHAPE"
    # Never log exception text, headers, raw response payloads, or secrets.
    ms = max(0, int((time.monotonic() - start) * 1000))
    result = "PASS" if passed else "FAIL"
    print(f"DEEPSEEK_PROBE={result};CATEGORY={category};HTTP_STATUS={status};MODEL={MODEL};ELAPSED_MS={ms}", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
