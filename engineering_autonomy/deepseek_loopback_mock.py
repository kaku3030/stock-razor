"""Test-only *loopback* DeepSeek-shaped HTTP boundary, no real provider egress.

This never reads or transmits DeepSeek credentials. It can send only to literal
127.0.0.1:port/v1/chat/completions, with proxies and redirects disabled.
There is NO Aider/LiteLLM interception: this is not production budget control.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from engineering_autonomy.deepseek_request_plan import (
    OfflineRequestPlan, RequestPlanDenied,
)

MAX_RESPONSE_BYTES = 16_384


class LoopbackDenied(ValueError):
    """Sanitized mock-transport rejection; never include server body or URL."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _validate_local_url(url: str) -> None:
    if type(url) is not str:
        raise LoopbackDenied("invalid mock destination")
    try:
        parsed = urllib.parse.urlsplit(url)
        valid = (
            parsed.scheme == "http"
            and parsed.netloc.startswith("127.0.0.1:")
            and parsed.hostname == "127.0.0.1"
            and parsed.port is not None
            and 1 <= parsed.port <= 65535
            and parsed.username is None
            and parsed.password is None
            and parsed.path == "/v1/chat/completions"
            and not parsed.query and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise LoopbackDenied("invalid mock destination")


class LoopbackMockTransport:
    """At most one mock HTTP attempt per sealed envelope in one Python process.

    The HTTP endpoint must be an authorized local fake server. It is impossible
    to target DeepSeek, another hostname, a proxy, or a redirect with this
    transport. An isolated coding agent is NOT forced to use this class.
    """

    def __init__(self, *, plan: OfflineRequestPlan, endpoint: str) -> None:
        _validate_local_url(endpoint)
        self._plan = plan
        self._endpoint = endpoint
        # Explicitly disable system HTTP proxy variables and redirect following.
        self._client = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect,
        )

    def send_once(self, sealed_bytes: bytes) -> dict[str, int | str]:
        # Reject unknown/edited bytes and exact replays before any HTTP call.
        try:
            claimed_input, reserved_output = self._plan.claim_loopback_dispatch(sealed_bytes)
        except RequestPlanDenied as exc:
            raise LoopbackDenied(str(exc)) from None
        request = urllib.request.Request(
            self._endpoint,
            data=sealed_bytes,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer offline-placeholder-not-real",
            },
        )
        try:
            with self._client.open(request, timeout=2) as response:
                if response.status != 200:
                    raise LoopbackDenied("mock HTTP failure")
                response_bytes = response.read(MAX_RESPONSE_BYTES + 1)
            if len(response_bytes) > MAX_RESPONSE_BYTES:
                raise LoopbackDenied("mock response oversized")
            parsed = json.loads(response_bytes)
            if not isinstance(parsed, dict):
                raise LoopbackDenied("mock response malformed")
            usage = parsed.get("usage")
            if not isinstance(usage, dict):
                raise LoopbackDenied("mock usage absent")
            input_used = usage.get("prompt_tokens")
            output_used = usage.get("completion_tokens")
            if (type(input_used) is not int or type(output_used) is not int
                    or not 0 <= input_used <= claimed_input
                    or not 0 <= output_used <= reserved_output):
                raise LoopbackDenied("mock usage exceeds claim or invalid")
            return {
                "status": "SIMULATED_LOOPBACK_ONLY",
                "claimed_input_tokens": claimed_input,
                "input_tokens_simulated": input_used,
                "reserved_output_tokens": reserved_output,
                "output_tokens_simulated": output_used,
            }
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeError,
                json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, LoopbackDenied):
                raise
            raise LoopbackDenied("mock HTTP or response failure") from None
