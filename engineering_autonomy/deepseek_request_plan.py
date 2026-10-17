"""Offline-only request-envelope planning for a future DeepSeek cost gate.

This module performs NO HTTP, does not read API keys and cannot authorize paid
execution. Input token counts are caller claims, not independently verified
provider usage. A real deployment must authenticate its tokenizer, meter all
requests/retries, enforce a provider-side spend cap, and prevent direct Aider
egress; this module is insufficient as an admission mechanism.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from threading import Lock


MODEL = "deepseek-flash"
MAX_REQUESTS = 2
MAX_INPUT_TOKENS = 20_000
MAX_OUTPUT_TOKENS = 4_000
MAX_MESSAGES = 64
MAX_PAYLOAD_BYTES = 64_000
ROLES = frozenset({"system", "user", "assistant"})


class RequestPlanDenied(ValueError):
    """Fail-closed offline planning rejection (never a provider response)."""


def _positive_integer(value: object) -> bool:
    return type(value) is int and value > 0


def _validate_messages(messages: object) -> list[dict[str, str]]:
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise RequestPlanDenied("message count not allowed")
    checked: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise RequestPlanDenied("unsupported message structure")
        role, message = item["role"], item["content"]
        if type(role) is not str or role not in ROLES or type(message) is not str or not message:
            raise RequestPlanDenied("unsupported role or content")
        checked.append({"role": role, "content": message})
    try:
        size = len(json.dumps(checked, ensure_ascii=False).encode("utf-8"))
    except UnicodeError as exc:
        raise RequestPlanDenied("invalid message encoding") from exc
    if size > MAX_PAYLOAD_BYTES:
        raise RequestPlanDenied("message payload too large")
    return checked


@dataclass
class OfflineRequestPlan:
    """Reservation of worst-case output, without transport or payment authority.

    Reservations are never refunded based on Aider analytics. A request can
    spend up to its server-enforced max_tokens even if its eventual response
    contains fewer tokens.  Input counts are UNVERIFIED estimates here.
    """

    requests_reserved: int = 0
    input_tokens_claimed: int = 0
    output_tokens_reserved: int = 0
    _history: list[dict[str, object]] = field(default_factory=list, repr=False)
    _seen_envelopes: set[str] = field(default_factory=set, repr=False)
    _claims: dict[str, tuple[int, int]] = field(default_factory=dict, repr=False)
    _dispatched: set[str] = field(default_factory=set, repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def reserve(
        self,
        *,
        model: str,
        messages: object,
        claimed_input_tokens: object,
        max_tokens: object,
        stream: bool = False,
        retry: bool = False,
    ) -> bytes:
        """Return immutable JSON bytes; never an editable post-check mapping."""
        if model != MODEL or stream is not False or retry is not False:
            raise RequestPlanDenied("unsupported model, stream or retry")
        if not _positive_integer(claimed_input_tokens) or not _positive_integer(max_tokens):
            raise RequestPlanDenied("missing or invalid token budget")
        message_list = _validate_messages(messages)
        payload: dict[str, object] = {
            "model": MODEL,
            "messages": message_list,
            "max_tokens": max_tokens,
            "stream": False,
            "thinking": {"type": "disabled"},
        }
        # An exact envelope replay can be a hidden accidental retry.
        # Only the SHA-256 fingerprint is kept in memory, never message text.
        try:
            wire_payload = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
        except UnicodeError as exc:
            raise RequestPlanDenied("invalid request encoding") from exc
        fingerprint = hashlib.sha256(wire_payload).hexdigest()
        # Atomic reservation against simultaneous callers in ONE Python process.
        # This is not a cross-process transaction or a network-transport guard.
        with self._lock:
            if fingerprint in self._seen_envelopes:
                raise RequestPlanDenied("duplicate envelope replay denied")
            if self.requests_reserved >= MAX_REQUESTS:
                raise RequestPlanDenied("request budget exhausted")
            if self.input_tokens_claimed + claimed_input_tokens > MAX_INPUT_TOKENS:
                raise RequestPlanDenied("input budget exhausted")
            if self.output_tokens_reserved + max_tokens > MAX_OUTPUT_TOKENS:
                raise RequestPlanDenied("output reservation exhausted")
            self.requests_reserved += 1
            self.input_tokens_claimed += claimed_input_tokens
            self.output_tokens_reserved += max_tokens
            self._seen_envelopes.add(fingerprint)
            self._claims[fingerprint] = (claimed_input_tokens, max_tokens)
            self._history.append({
                "request": self.requests_reserved,
                "claimed_input_tokens": claimed_input_tokens,
                "reserved_output_tokens": max_tokens,
                "evidence": "UNVERIFIED_INPUT_COUNT",
            })
        # These bytes cannot be modified in-place after pre-request reservation.
        # Only a future transport that sends these exact bytes can claim
        # on-wire enforcement; this offline planner does not send anything.
        return wire_payload

    def claim_loopback_dispatch(self, sealed_bytes: bytes) -> tuple[int, int]:
        """Atomic one-shot claim for the separately isolated mock transport.

        Even failed HTTP attempts spend their claim. This is per-process state,
        not an upstream API firewall or cross-run billing ledger.
        """
        if type(sealed_bytes) is not bytes:
            raise RequestPlanDenied("not a sealed request")
        digest = hashlib.sha256(sealed_bytes).hexdigest()
        with self._lock:
            if digest not in self._seen_envelopes:
                raise RequestPlanDenied("request bytes were not admitted")
            if digest in self._dispatched:
                raise RequestPlanDenied("request dispatch replay denied")
            self._dispatched.add(digest)
            return self._claims[digest]

    def sanitized_summary(self) -> dict[str, int | str]:
        with self._lock:
            return {
                "status": "OFFLINE_ONLY_NOT_BILLING_PROOF",
                "requests_reserved": self.requests_reserved,
                "input_tokens_claimed": self.input_tokens_claimed,
                "output_tokens_reserved": self.output_tokens_reserved,
            }
