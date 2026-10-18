"""Opt-in, single-request research model transport with a killable local worker.

No scheduler/config discovery, fallback, tools, streaming or paid smoke tests.
The durable AI consumer owns call admission and uncertain-result reconciliation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from src.llm.generation_backend import (
    GenerationCapabilities, GenerationError, GenerationErrorCode, GenerationResult,
)

# Security allowlist, not operator-selected endpoints or environment defaults.
_BASE_URLS = {"openai": "https://api.openai.com/v1", "deepseek": "https://api.deepseek.com"}
_MODULE = "src.services.stock_radar_v2.research_ai_backend"
_MAX_WIRE_BYTES = 65536
_MAX_TEXT_BYTES = 16384
_COUNTS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _error(code=GenerationErrorCode.UNKNOWN_BACKEND_ERROR):
    return GenerationError(code, stage="research_request", retryable=False,
                           fallbackable=False, backend="radar_single_request")


def _validate(payload):
    if not isinstance(payload, dict) or set(payload) != {
        "provider", "model", "api_key", "prompt", "system_prompt", "timeout",
        "max_output_tokens", "request_id",
    }:
        raise ValueError("invalid research request")
    if payload["provider"] not in _BASE_URLS:
        raise ValueError("unsupported research provider")
    if not isinstance(payload["model"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", payload["model"]):
        raise ValueError("invalid research model")
    key = payload["api_key"]
    if not isinstance(key, str) or not 1 <= len(key) <= 4096 or any(ch.isspace() for ch in key):
        raise ValueError("invalid research credential")
    for field, bound in (("prompt", _MAX_TEXT_BYTES), ("system_prompt", 4096)):
        value = payload[field]
        if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > bound:
            raise ValueError("invalid research text bound")
    for field, bound in (("timeout", 60), ("max_output_tokens", 2048)):
        if type(payload[field]) is not int or not 1 <= payload[field] <= bound:
            raise ValueError("invalid research execution bound")
    if not isinstance(payload["request_id"], str) or not re.fullmatch(r"[0-9a-f]{64}", payload["request_id"]):
        raise ValueError("invalid research request identity")


def _request_once(payload, *, transport=None):
    """Use the installed official SDK; transport injection is an offline test seam."""
    _validate(payload)
    import httpx
    import openai

    with httpx.Client(timeout=payload["timeout"], trust_env=False,
                      follow_redirects=False, transport=transport) as http_client:
        with openai.OpenAI(api_key=payload["api_key"], base_url=_BASE_URLS[payload["provider"]],
                           max_retries=0, timeout=payload["timeout"], http_client=http_client) as client:
            # HTTP streaming here bounds response bytes; the model request is non-streaming.
            token_field = "max_completion_tokens" if payload["provider"] == "openai" else "max_tokens"
            with client.chat.completions.with_streaming_response.create(
                model=payload["model"], stream=False,
                messages=[{"role": "system", "content": payload["system_prompt"]},
                          {"role": "user", "content": payload["prompt"]}],
                **{token_field: payload["max_output_tokens"]},
                extra_headers={"X-Client-Request-Id": payload["request_id"]},
            ) as response:
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=4096):
                    body.extend(chunk)
                    if len(body) > _MAX_WIRE_BYTES:
                        raise ValueError("research response exceeds byte bound")
    data = json.loads(body)
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("research response choice not verified")
    choice = choices[0]
    message = choice.get("message", {})
    text = message.get("content")
    if (choice.get("finish_reason") != "stop" or message.get("tool_calls")
            or message.get("function_call") or message.get("refusal")
            or not isinstance(text, str) or not text.strip()
            or len(text.encode("utf-8")) > _MAX_TEXT_BYTES):
        raise ValueError("research response not verified")
    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("research token evidence missing")
    counts = {name: usage.get(name) for name in _COUNTS}
    if (any(type(value) is not int or value < 0 for value in counts.values())
            or counts["total_tokens"] <= 0
            or counts["total_tokens"] != counts["prompt_tokens"] + counts["completion_tokens"]
            or counts["completion_tokens"] > payload["max_output_tokens"]):
        raise ValueError("research token evidence not verified")
    # Never transfer provider metadata, extra usage fields, raw bodies or credentials.
    return {"text": text, "usage": counts}


class ResearchAIRequestBackend:
    """GenerationBackend for the durable research consumer, disabled by default.

    Explicit enabled=True is not production/billing authorization. The caller must
    separately admit the request through RadarAIEventConsumer's durable budget.
    No environment credential lookup or health/smoke model request is performed.
    """
    backend_id = "radar_single_request"
    capabilities = GenerationCapabilities(True, False, False, False, False, False)

    def __init__(self, *, provider: str, model: str, api_key: str, enabled: bool = False):
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        self._provider, self._model, self._api_key = provider, model, api_key
        self._enabled = enabled

    def generate(self, prompt, generation_config, *, system_prompt=None, stream=False,
                 stream_progress_callback=None, response_validator=None, audit_context=None):
        if not self._enabled:
            raise _error(GenerationErrorCode.BACKEND_NOT_CONFIGURED)
        if (stream is not False or stream_progress_callback is not None
                or not isinstance(audit_context, dict)
                or not isinstance(generation_config, dict)
                or set(generation_config) != {"timeout", "max_output_tokens"}):
            raise _error(GenerationErrorCode.UNSAFE_CONFIG)
        payload = {"provider": self._provider, "model": self._model, "api_key": self._api_key,
                   "prompt": prompt, "system_prompt": system_prompt,
                   "request_id": (audit_context or {}).get("request_id"), **generation_config}
        try:
            _validate(payload)
            wire = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(wire) > _MAX_WIRE_BYTES:
                raise ValueError("request too large")
        except (TypeError, ValueError, UnicodeError):
            raise _error(GenerationErrorCode.UNSAFE_CONFIG) from None
        # Fixed module, no shell/arbitrary command. Credentials travel over stdin,
        # never argv, files, inherited SDK/proxy/debug configuration or stderr.
        env = {name: value for name, value in os.environ.items()
               if name.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG"}}
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                [sys.executable, "-E", "-X", "utf8", "-m", _MODULE],
                cwd=Path(__file__).resolve().parents[3], env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except OSError:
            raise _error() from None
        try:
            output, _ = process.communicate(wire, timeout=max(0.001, payload["timeout"] - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            raise _error(GenerationErrorCode.TIMEOUT) from None
        except OSError:
            raise _error() from None
        finally:
            # Fixed SDK worker cannot launch tools/children. Local termination
            # does not cancel remote provider work or prove a zero charge.
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                raise _error() from None  # cleanup unverified; never retry
            finally:
                for pipe in (process.stdin, process.stdout):
                    if pipe is not None:
                        pipe.close()
        try:
            if process.returncode != 0 or len(output) > _MAX_WIRE_BYTES:
                raise ValueError("worker result not verified")
            result = json.loads(output)
            if set(result) != {"text", "usage"}:
                raise ValueError("unexpected worker fields")
            # Consumer validates schema, complete token evidence and event identity.
            generated = GenerationResult(text=result["text"], usage=result["usage"],
                model=self._model, provider=self._provider, backend=self.backend_id,
                diagnostics={"research_only": True, "cost_status": "UNKNOWN"})
            if response_validator is not None:
                response_validator(generated.text)
            return generated
        except Exception:
            raise _error(GenerationErrorCode.SCHEMA_VALIDATION_FAILED) from None


def _worker_main():
    """Private fixed worker protocol; never print exception/SDK/provider text."""
    try:
        payload = sys.stdin.buffer.read(_MAX_WIRE_BYTES + 1)
        if len(payload) > _MAX_WIRE_BYTES:
            return 1
        result = _request_once(json.loads(payload))
        wire = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(wire) > _MAX_WIRE_BYTES:
            return 1
        sys.stdout.buffer.write(wire)
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(_worker_main())
