"""No-network acceptance matrix for future request-boundary planning.

These tests prove only local envelope checks. They do NOT validate provider
billing, input-token counting, direct-network bypass prevention or Aider retries.
"""
import pytest

from engineering_autonomy.deepseek_request_plan import (
    MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS, MODEL, OfflineRequestPlan, RequestPlanDenied,
)


MESSAGES = [{"role": "user", "content": "Add one regression test."}]


def test_two_requests_fit_only_exact_worst_case_reserved_budget():
    ledger = OfflineRequestPlan()
    first = ledger.reserve(
        model=MODEL, messages=MESSAGES, claimed_input_tokens=12_000, max_tokens=2_500
    )
    second = ledger.reserve(
        model=MODEL, messages=MESSAGES, claimed_input_tokens=8_000, max_tokens=1_500
    )
    assert first == {
        "model": MODEL, "messages": MESSAGES,
        "max_tokens": 2_500, "stream": False, "thinking": {"type": "disabled"},
    }
    assert second["max_tokens"] == 1_500
    assert ledger.sanitized_summary() == {
        "status": "OFFLINE_ONLY_NOT_BILLING_PROOF",
        "requests_reserved": 2, "input_tokens_claimed": MAX_INPUT_TOKENS,
        "output_tokens_reserved": MAX_OUTPUT_TOKENS,
    }
    with pytest.raises(RequestPlanDenied, match="request budget exhausted"):
        ledger.reserve(
            model=MODEL, messages=MESSAGES, claimed_input_tokens=1, max_tokens=1
        )


@pytest.mark.parametrize("field,value", [
    ("model", "deepseek-v4-pro"),
    ("model", "deepseek-chat"),
    ("stream", True),
    ("stream", 0),
    ("retry", True),
    ("retry", 0),
    ("claimed_input_tokens", None),
    ("claimed_input_tokens", 0),
    ("claimed_input_tokens", -1),
    ("claimed_input_tokens", True),
    ("claimed_input_tokens", 20001),
    ("max_tokens", None),
    ("max_tokens", 0),
    ("max_tokens", True),
    ("max_tokens", -1),
    ("max_tokens", 4001),
    ("messages", []),
    ("messages", None),
    ("messages", [{}]),
    ("messages", [{"role": "tool", "content": "call"}]),
    ("messages", [{"role": [], "content": "hello"}]),
    ("messages", [{"role": "user", "content": ""}]),
    ("messages", [{"role": "user", "content": ["image"]}]),
    ("messages", [{"role": "user", "content": "hello", "tool_calls": []}]),
    ("messages", [{"role": "user", "content": "x" * 65000}]),
    ("messages", [{"role": "user", "content": "\ud800"}]),
])
def test_malformed_and_unbounded_requests_fail_without_consuming_a_slot(field, value):
    ledger = OfflineRequestPlan()
    args = {
        "model": MODEL, "messages": MESSAGES,
        "claimed_input_tokens": 15, "max_tokens": 40,
    }
    args[field] = value
    with pytest.raises(RequestPlanDenied):
        ledger.reserve(**args)
    assert ledger.sanitized_summary()["requests_reserved"] == 0


def test_cross_call_budget_is_reserved_before_send_and_not_recycled():
    ledger = OfflineRequestPlan()
    ledger.reserve(
        model=MODEL, messages=MESSAGES, claimed_input_tokens=19_999, max_tokens=3_999
    )
    with pytest.raises(RequestPlanDenied, match="input budget exhausted"):
        ledger.reserve(
            model=MODEL, messages=MESSAGES, claimed_input_tokens=2, max_tokens=1
        )
    with pytest.raises(RequestPlanDenied, match="output reservation exhausted"):
        ledger.reserve(
            model=MODEL, messages=MESSAGES, claimed_input_tokens=1, max_tokens=2
        )
    assert ledger.sanitized_summary()["requests_reserved"] == 1
    ledger.reserve(
        model=MODEL, messages=MESSAGES, claimed_input_tokens=1, max_tokens=1
    )
    assert ledger.sanitized_summary()["requests_reserved"] == 2


def test_input_text_does_not_leak_to_sanitized_summary():
    ledger = OfflineRequestPlan()
    secret = "PLEASE DO NOT LOG SOURCE TEXT"
    ledger.reserve(
        model=MODEL, messages=[{"role": "user", "content": secret}],
        claimed_input_tokens=10, max_tokens=1,
    )
    assert secret not in repr(ledger.sanitized_summary())
