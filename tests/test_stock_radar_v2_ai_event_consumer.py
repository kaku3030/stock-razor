"""Durable consumer tests with a deterministic GenerationBackend, no API I/O."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.llm.generation_backend import GenerationResult
from src.services.stock_radar_v2.bar_event_ledger import ClosedBarEventCandidate, RadarBarEventLedger
from src.services.stock_radar_v2.ai_event_consumer import RadarAIEventConsumer, AIConsumerLimits

NOW = datetime(2026, 10, 16, 15, 0, 5, tzinfo=timezone.utc)
SHA = "a" * 40


def event(**changes):
    values = dict(
        provider_id="futu", symbol="US.AMD", timeframe="15m",
        bar_end=NOW - timedelta(seconds=5), observed_at=NOW,
        exchange_timezone="America/New_York", session_id="2026-10-16",
        session_status="CONFIRMED", freshness_status="FRESH", quality_status="PASS",
        quality_flags=(), open=100, high=102, low=99, close=101,
        volume=1000, turnover=101000, source_revision=SHA,
        source_runtime_id="offline-source", source_sequence=1,
        rule_id="canonical_closed_bar", rule_revision="1", signal_kind="closed_bar_observation",
        evidence={"provider_feed": "opend"}, is_closed=True, is_complete=True,
    )
    values.update(changes)
    return ClosedBarEventCandidate(**values)


class Backend:
    backend_id = "offline-test"

    def __init__(self, outcome=None):
        self.calls = []
        self.outcome = outcome

    def generate(self, prompt, generation_config, **kwargs):
        self.calls.append((prompt, generation_config, kwargs))
        if self.outcome:
            return self.outcome(prompt, generation_config, kwargs)
        payload = json.loads(prompt)
        return GenerationResult(
            text=json.dumps({"event_id": payload["event_id"], "assessment": "WATCH", "evidence_fields": ["close", "volume"]}),
            model="offline-model", provider="offline", backend=self.backend_id,
            usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )


def consumer(ledger, backend, clock, **kwargs):
    return RadarAIEventConsumer(
        ledger, backend=backend, expected_source_sha=SHA, worker_id="consumer-1",
        now=lambda: clock[0], enabled=True, **kwargs,
    )


def test_disabled_default_does_not_claim_or_call(tmp_path):
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        saved = ledger.record(event(), recorded_at=NOW)
        backend = Backend()
        c = RadarAIEventConsumer(ledger, backend=backend, expected_source_sha=SHA, worker_id="off")
        assert c.poll_once().status == "DISABLED"
        assert ledger.get(saved.event.idempotency_key).attempts == 0
        assert backend.calls == []


def test_generation_receipt_is_durable_and_idempotent(tmp_path):
    path = tmp_path / "events.sqlite"
    backend, clock = Backend(), [NOW]
    with RadarBarEventLedger(path) as ledger:
        saved = ledger.record(event(), recorded_at=NOW)
        result = consumer(ledger, backend, clock).poll_once()
        assert result.status == "COMPLETED"
        record = ledger.get_ai_wake(saved.event.idempotency_key, now=NOW)
        assert record.status == "SUCCEEDED"
        assert record.result["assessment"] == "WATCH"
        assert record.usage["total_tokens"] == 120
        assert ledger.get(saved.event.idempotency_key).status == "ACKNOWLEDGED"
        assert len(backend.calls) == 1
        _, config, audit = backend.calls[0]
        assert config["timeout"] == 10
        assert config["max_output_tokens"] == 512
        assert audit["audit_context"]["idempotency_key"] == saved.event.idempotency_key
        assert result.to_dict()["radar_admission"] == "BLOCKED"
        assert result.to_dict()["live_trade"] is False
    with RadarBarEventLedger(path) as ledger:
        ledger.record(event(), recorded_at=NOW)
        assert consumer(ledger, backend, clock).poll_once().status == "IDLE"
        assert len(backend.calls) == 1


def test_success_persisted_before_ack_recovers_without_model_replay(tmp_path):
    path = tmp_path / "events.sqlite"
    backend, clock = Backend(), [NOW]
    with RadarBarEventLedger(path) as ledger:
        saved = ledger.record(event(), recorded_at=NOW)
        original = ledger.acknowledge
        ledger.acknowledge = lambda *a, **k: (_ for _ in ()).throw(PermissionError("lease lost"))
        result = consumer(ledger, backend, clock).poll_once()
        assert result.status == "ACK_PENDING"
        assert ledger.get_ai_wake(saved.event.idempotency_key, now=NOW).status == "SUCCEEDED"
        ledger.acknowledge = original
    clock[0] += timedelta(seconds=200)  # recovery is not a fresh model invocation
    with RadarBarEventLedger(path) as ledger:
        result = consumer(ledger, backend, clock).poll_once()
        assert result.status == "RECOVERED"
        assert ledger.get(saved.event.idempotency_key).status == "ACKNOWLEDGED"
    assert len(backend.calls) == 1


def test_crash_after_durable_start_blocks_reinvocation_across_reopen(tmp_path):
    path = tmp_path / "events.sqlite"
    with RadarBarEventLedger(path) as ledger:
        saved = ledger.record(event(), recorded_at=NOW)
        claim = ledger.claim_next(worker_id="crashed", now=NOW, lease_seconds=40)
        reservation = ledger.begin_ai_wake(claim, now=NOW, timeout_seconds=10, max_calls=2)
        assert reservation.created is True
    clock, backend = [NOW + timedelta(seconds=41)], Backend()
    with RadarBarEventLedger(path) as ledger:
        result = consumer(ledger, backend, clock, limits=AIConsumerLimits(max_calls=2)).poll_once()
        assert result.status == "UNKNOWN"
        assert ledger.get_ai_wake(saved.event.idempotency_key, now=clock[0]).status == "UNKNOWN"
        assert backend.calls == []


def test_lease_theft_or_expiry_cannot_start_ai(tmp_path):
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        ledger.record(event(), recorded_at=NOW)
        claim = ledger.claim_next(worker_id="old", now=NOW, lease_seconds=1)
        with pytest.raises(PermissionError):
            ledger.begin_ai_wake(claim, now=NOW + timedelta(seconds=2), timeout_seconds=10, max_calls=1)


def test_same_event_cannot_reserve_second_invocation(tmp_path):
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        ledger.record(event(), recorded_at=NOW)
        claim = ledger.claim_next(worker_id="one", now=NOW, lease_seconds=40)
        first = ledger.begin_ai_wake(claim, now=NOW, timeout_seconds=10, max_calls=1)
        again = ledger.begin_ai_wake(claim, now=NOW, timeout_seconds=10, max_calls=1)
        assert first.created is True and again.created is False
        assert first.record.request_id == again.record.request_id


@pytest.mark.parametrize("kind", ["timeout", "bad_json", "wrong_event", "trade_decision", "extra_field", "missing_usage", "too_many_tokens", "late"])
def test_uncertain_or_invalid_result_never_retries_or_persists_raw_output(tmp_path, kind):
    clock = [NOW]
    def outcome(prompt, config, kwargs):
        if kind == "timeout": raise TimeoutError("private https://credentials.invalid secret")
        payload = {"event_id": json.loads(prompt)["event_id"], "assessment": "WATCH", "evidence_fields": ["close"]}
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        if kind == "wrong_event": payload["event_id"] = "b" * 64
        if kind == "trade_decision": payload["assessment"] = "BUY"
        if kind == "extra_field": payload["webhook"] = "private-secret"
        if kind == "missing_usage": usage = {}
        if kind == "too_many_tokens": usage = {"prompt_tokens": 100, "completion_tokens": 600, "total_tokens": 700}
        if kind == "late": clock[0] += timedelta(seconds=11)
        return GenerationResult(text="private-secret" if kind == "bad_json" else json.dumps(payload), model="offline", provider="offline", backend="offline", usage=usage)
    backend = Backend(outcome)
    path = tmp_path / "events.sqlite"
    with RadarBarEventLedger(path) as ledger:
        saved = ledger.record(event(), recorded_at=NOW)
        assert consumer(ledger, backend, clock).poll_once().status == "UNKNOWN"
        assert ledger.get_ai_wake(saved.event.idempotency_key, now=clock[0]).result is None
    clock[0] += timedelta(seconds=80)
    with RadarBarEventLedger(path) as ledger:
        assert consumer(ledger, backend, clock).poll_once().status == "UNKNOWN"
        assert len(backend.calls) == 1
    assert b"private-secret" not in path.read_bytes()
    assert b"credentials.invalid" not in path.read_bytes()


@pytest.mark.parametrize("changes", [
    {"source_revision": "b" * 40}, {"bar_end": NOW - timedelta(minutes=3)},
    {"signal_kind": "candidate"}, {"provider_id": "other"},
    {"timeframe": "1m"}, {"evidence": {"provider_feed": "other"}},
])
def test_unqualified_event_does_not_invoke_backend(tmp_path, changes):
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        ledger.record(event(**changes), recorded_at=NOW)
        backend = Backend()
        assert consumer(ledger, backend, [NOW]).poll_once().status == "BLOCKED"
        assert backend.calls == []


def test_persistent_call_budget_survives_new_consumer(tmp_path):
    path = tmp_path / "events.sqlite"
    clock, backend = [NOW], Backend()
    with RadarBarEventLedger(path) as ledger:
        ledger.record(event(), recorded_at=NOW)
        assert consumer(ledger, backend, clock).poll_once().status == "COMPLETED"
    with RadarBarEventLedger(path) as ledger:
        ledger.record(event(symbol="US.NVDA"), recorded_at=NOW)
        result = consumer(ledger, backend, clock).poll_once()
        assert result.status == "BLOCKED"
        assert result.reason == "AI_CALL_BUDGET_EXHAUSTED"
        assert len(backend.calls) == 1


def test_unknown_call_blocks_other_events_even_with_budget_left(tmp_path):
    clock, backend = [NOW], Backend(lambda *_: (_ for _ in ()).throw(TimeoutError()))
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        ledger.record(event(), recorded_at=NOW)
        assert consumer(ledger, backend, clock, limits=AIConsumerLimits(max_calls=3)).poll_once().status == "UNKNOWN"
        ledger.record(event(symbol="US.NVDA"), recorded_at=NOW)
        result = consumer(ledger, backend, clock, limits=AIConsumerLimits(max_calls=3)).poll_once()
        assert result.status == "BLOCKED"
        assert result.reason == "AI_UNRESOLVED_INVOCATION"
        assert len(backend.calls) == 1


@pytest.mark.parametrize("usage", [
    {"prompt_tokens": -1, "completion_tokens": 20, "total_tokens": 20},
    {"prompt_tokens": True, "completion_tokens": 20, "total_tokens": 21},
    {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 999},
    {"prompt_tokens": 100, "total_tokens": 100},
])
def test_invalid_or_incomplete_usage_stays_unknown(tmp_path, usage):
    def outcome(prompt, config, kwargs):
        return GenerationResult(text=json.dumps({"event_id": json.loads(prompt)["event_id"], "assessment": "WATCH", "evidence_fields": ["close"]}), model="offline", provider="offline", backend="offline", usage=usage)
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        ledger.record(event(), recorded_at=NOW)
        assert consumer(ledger, Backend(outcome), [NOW]).poll_once().status == "UNKNOWN"


def test_two_connections_cannot_dispatch_while_another_invocation_is_running(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered, release = Event(), Event()
    def outcome(prompt, config, kwargs):
        entered.set()
        assert release.wait(3)
        return Backend().generate(prompt, config, **kwargs)
    backend, path = Backend(outcome), tmp_path / "events.sqlite"
    with RadarBarEventLedger(path) as first, RadarBarEventLedger(path) as second:
        first.record(event(), recorded_at=NOW)
        first.record(event(symbol="US.NVDA"), recorded_at=NOW)
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(consumer(first, backend, [NOW], limits=AIConsumerLimits(max_calls=2)).poll_once)
            try:
                assert entered.wait(3)
                result = consumer(second, backend, [NOW], limits=AIConsumerLimits(max_calls=2)).poll_once()
                assert result.status == "BLOCKED"
                assert result.reason == "AI_UNRESOLVED_INVOCATION"
                assert len(backend.calls) == 1
            finally:
                release.set()
            assert running.result(timeout=3).status == "COMPLETED"


def test_real_sqlite_failure_before_intent_never_dispatches(tmp_path):
    import sqlite3
    path, backend = tmp_path / "events.sqlite", Backend()
    with RadarBarEventLedger(path) as ledger:
        ledger.record(event(), recorded_at=NOW)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TRIGGER reject_ai BEFORE INSERT ON stock_radar_ai_wake BEGIN SELECT RAISE(ABORT,'private-details'); END")
        result = consumer(ledger, backend, [NOW]).poll_once()
        assert result.status == "BLOCKED"
        assert backend.calls == []
        assert "private-details" not in json.dumps(result.to_dict())


def test_wrong_invocation_token_cannot_complete_or_change_status(tmp_path):
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        saved = ledger.record(event(), recorded_at=NOW)
        claim = ledger.claim_next(worker_id="one", now=NOW, lease_seconds=40)
        ledger.begin_ai_wake(claim, now=NOW, timeout_seconds=10, max_calls=1)
        with pytest.raises(PermissionError):
            ledger.mark_ai_wake_unknown(saved.event.idempotency_key, invocation_token="other")
        assert ledger.get_ai_wake(saved.event.idempotency_key, now=NOW).status == "STARTED"


@pytest.mark.parametrize("limits", [{"max_calls": True}, {"timeout_seconds": 61}, {"max_output_tokens": 0}, {"max_event_age_seconds": 121}])
def test_unsafe_consumer_limits_are_rejected(limits):
    with pytest.raises(ValueError):
        AIConsumerLimits(**limits)


def test_expiry_is_persisted_when_a_different_event_is_blocked(tmp_path):
    with RadarBarEventLedger(tmp_path / "events.sqlite") as ledger:
        first = ledger.record(event(), recorded_at=NOW)
        claim = ledger.claim_next(worker_id="first", now=NOW, lease_seconds=40)
        ledger.begin_ai_wake(claim, now=NOW, timeout_seconds=1, max_calls=2)
        second = ledger.record(event(symbol="US.NVDA"), recorded_at=NOW)
        next_claim = ledger.claim_next(worker_id="second", now=NOW + timedelta(seconds=2), lease_seconds=40)
        from src.services.stock_radar_v2.bar_event_ledger import AIWakeBlocked
        with pytest.raises(AIWakeBlocked, match="AI_UNRESOLVED_INVOCATION"):
            ledger.begin_ai_wake(next_claim, now=NOW + timedelta(seconds=2), timeout_seconds=1, max_calls=2)
        # Reading at the earlier instant cannot manufacture the classification.
        assert ledger.get_ai_wake(first.event.idempotency_key, now=NOW).status == "UNKNOWN"
        with pytest.raises(KeyError):
            ledger.get_ai_wake(second.event.idempotency_key, now=NOW)
