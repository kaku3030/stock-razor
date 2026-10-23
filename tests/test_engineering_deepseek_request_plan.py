"""No-network acceptance matrix for future request-boundary planning.

These tests prove only local envelope checks. They do NOT validate provider
billing, input-token counting, direct-network bypass prevention or Aider retries.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json

import pytest

from engineering_autonomy.deepseek_request_plan import (
    MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS, MODEL, OfflineRequestPlan, RequestPlanDenied,
)


MESSAGES = [{"role": "user", "content": "Add one regression test."}]


def test_two_requests_fit_only_exact_worst_case_reserved_budget():
    ledger = OfflineRequestPlan()
    first_wire = ledger.reserve(
        model=MODEL, messages=MESSAGES, claimed_input_tokens=12_000, max_tokens=2_500
    )
    second_wire = ledger.reserve(
        model=MODEL, messages=MESSAGES, claimed_input_tokens=8_000, max_tokens=1_500
    )
    assert isinstance(first_wire, bytes) and isinstance(second_wire, bytes)
    first = json.loads(first_wire)
    second = json.loads(second_wire)
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


def test_exact_duplicate_replay_is_denied_without_extra_reservation():
    ledger = OfflineRequestPlan()
    kwargs = {
        "model": MODEL, "messages": MESSAGES,
        "claimed_input_tokens": 123, "max_tokens": 456,
    }
    ledger.reserve(**kwargs)
    with pytest.raises(RequestPlanDenied, match="duplicate envelope replay denied"):
        ledger.reserve(**kwargs)
    assert ledger.sanitized_summary()["requests_reserved"] == 1
    assert ledger.sanitized_summary()["output_tokens_reserved"] == 456


def test_parallel_distinct_envelopes_do_not_oversubscribe_single_process():
    ledger = OfflineRequestPlan()
    workers = 12
    start = Barrier(workers)

    def attempt(index):
        start.wait(timeout=15)
        try:
            ledger.reserve(
                model=MODEL,
                messages=[{"role": "user", "content": f"unique attempt {index}"}],
                claimed_input_tokens=1,
                max_tokens=1,
            )
            return True
        except RequestPlanDenied:
            return False

    with ThreadPoolExecutor(max_workers=workers) as executor:
        outcome = list(executor.map(attempt, range(workers)))
    assert sum(outcome) == 2
    assert ledger.sanitized_summary() == {
        "status": "OFFLINE_ONLY_NOT_BILLING_PROOF",
        "requests_reserved": 2,
        "input_tokens_claimed": 2,
        "output_tokens_reserved": 2,
    }


def test_parallel_same_envelope_is_deduplicated_not_counted_twice():
    ledger = OfflineRequestPlan()
    workers = 8
    start = Barrier(workers)

    def attempt(_):
        start.wait(timeout=15)
        try:
            ledger.reserve(
                model=MODEL, messages=MESSAGES, claimed_input_tokens=50, max_tokens=50
            )
            return "accepted"
        except RequestPlanDenied as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        outcomes = list(executor.map(attempt, range(workers)))
    assert outcomes.count("accepted") == 1
    assert outcomes.count("duplicate envelope replay denied") == workers - 1
    assert ledger.sanitized_summary()["requests_reserved"] == 1


def test_each_process_plan_is_independent_and_not_a_distributed_ledger():
    first = OfflineRequestPlan()
    second = OfflineRequestPlan()
    request = {
        "model": MODEL, "messages": MESSAGES,
        "claimed_input_tokens": 1, "max_tokens": 1,
    }
    assert first.reserve(**request) == second.reserve(**request)
    assert first.sanitized_summary()["requests_reserved"] == 1
    assert second.sanitized_summary()["requests_reserved"] == 1


def test_emitted_wire_envelope_is_not_mutable_after_pre_send_validation():
    ledger = OfflineRequestPlan()
    source_messages = [{"role": "user", "content": "Never modify after signing"}]
    payload = ledger.reserve(
        model=MODEL, messages=source_messages, claimed_input_tokens=50,
        max_tokens=400,
    )
    assert type(payload) is bytes
    before = bytes(payload)
    with pytest.raises(TypeError):
        payload[0] = 12
    original = json.loads(payload)
    original["max_tokens"] = 9000
    source_messages[0]["content"] = "mutated after reserve"
    assert json.loads(payload)["max_tokens"] == 400
    assert json.loads(payload)["messages"] == [
        {"role": "user", "content": "Never modify after signing"}
    ]
    assert payload == before
    assert ledger.sanitized_summary()["output_tokens_reserved"] == 400


def test_immutable_wire_bytes_can_be_reused_only_by_an_external_transport():
    # The planner does not send requests and cannot stop someone from
    # re-parsing and forging new bytes outside its API.
    ledger = OfflineRequestPlan()
    sealed = ledger.reserve(
        model=MODEL, messages=MESSAGES, claimed_input_tokens=100, max_tokens=500
    )
    tampered_copy = json.loads(sealed)
    tampered_copy["max_tokens"] = 50_000
    assert json.loads(sealed)["max_tokens"] == 500
    assert tampered_copy["max_tokens"] != json.loads(sealed)["max_tokens"]
