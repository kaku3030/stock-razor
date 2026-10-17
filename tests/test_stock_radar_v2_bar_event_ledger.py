from datetime import datetime, timedelta, timezone
from dataclasses import fields

import pytest

from src.services.stock_radar_v2.bar_event_ledger import (
    ClosedBarEventCandidate,
    EventQueueFull,
    RadarBarEventLedger,
)


T0 = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)


def test_database_path_must_be_an_explicit_storage_decision():
    with pytest.raises(TypeError):
        RadarBarEventLedger()


def candidate(**changes):
    values = {
        "provider_id": "OpenD",
        "symbol": "US.AMD",
        "timeframe": "15m",
        "bar_end": T0,
        "observed_at": T0 + timedelta(seconds=2),
        "exchange_timezone": "America/New_York",
        "session_id": "US_REGULAR_2026-10-16",
        "session_status": "CONFIRMED",
        "freshness_status": "FRESH",
        "quality_status": "PASS",
        "quality_flags": (),
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1200.0,
        "turnover": 120600.0,
        "source_revision": "a" * 40,
        "source_runtime_id": "worker-1",
        "source_sequence": 42,
        "rule_id": "pullback",
        "rule_revision": "v1",
        "signal_kind": "candidate",
        "evidence": {"signal_state": "research_candidate"},
        "is_closed": True,
        "is_complete": True,
    }
    values.update(changes)
    return ClosedBarEventCandidate(**values)


@pytest.mark.parametrize("missing", ["is_closed", "is_complete"])
def test_closed_and_complete_attestations_are_required(missing):
    original = candidate()
    values = {item.name: getattr(original, item.name) for item in fields(original) if item.init}
    values.pop(missing)
    with pytest.raises(TypeError):
        ClosedBarEventCandidate(**values)


def test_candidate_evidence_is_snapshotted_before_external_mutation(tmp_path):
    evidence = {"technical": {"reason": "qualified"}}
    original = candidate(evidence=evidence)
    evidence["technical"]["api_key"] = "must-not-persist"
    original.evidence["technical"]["reason"] = "changed-after-validation"
    with RadarBarEventLedger(tmp_path / "immutable.sqlite") as ledger:
        saved = ledger.record(original)
    assert saved.event.payload["evidence"] == {"technical": {"reason": "qualified"}}


def test_candidate_quality_flags_do_not_follow_a_mutable_input(tmp_path):
    flags = []
    original = candidate(quality_flags=flags)
    flags.append("MISSING_BAR")
    with RadarBarEventLedger(tmp_path / "immutable-flags.sqlite") as ledger:
        saved = ledger.record(original)
    assert original.quality_flags == ()
    assert saved.event.payload["quality_flags"] == []


def test_event_identity_is_stable_and_contains_governed_signal_dimensions():
    first = candidate()
    offset_same_instant = candidate(
        bar_end=T0.astimezone(timezone(timedelta(hours=-4))),
        observed_at=(T0 + timedelta(seconds=2)).astimezone(timezone(timedelta(hours=-4))),
    )

    assert first.idempotency_key == offset_same_instant.idempotency_key
    assert first.idempotency_key == (
        "OpenD|US.AMD|15m|2026-10-16T20:00:00.000000Z|pullback|v1|candidate"
    )
    assert first.bar_id == offset_same_instant.bar_id
    assert candidate(rule_revision="v2").idempotency_key != first.idempotency_key


@pytest.mark.parametrize(
    "changes",
    [
        {"is_closed": False},
        {"is_complete": False},
        {"freshness_status": "UNKNOWN"},
        {"freshness_status": "STALE"},
        {"session_status": "UNKNOWN"},
        {"quality_status": "BLOCKED"},
        {"quality_flags": ("MISSING_BAR",)},
        {"high": float("nan")},
        {"close": 103.0},
        {"volume": -1.0},
        {"exchange_timezone": "Not/AZone"},
        {"observed_at": T0 - timedelta(seconds=1)},
        {"evidence": {"api_key": "must-not-persist"}},
        {"evidence": {"explanation": "https://private.example.invalid"}},
    ],
)
def test_candidates_fail_closed_on_unqualified_or_invalid_bar_evidence(changes):
    with pytest.raises(ValueError):
        candidate(**changes)


def test_duplicate_replay_is_durable_and_conflicting_same_key_is_rejected(tmp_path):
    path = tmp_path / "radar-events.sqlite"
    with RadarBarEventLedger(path) as ledger:
        original = ledger.record(candidate())
        duplicate = ledger.record(candidate(observed_at=T0 + timedelta(seconds=5)))

    with RadarBarEventLedger(path) as reopened:
        replay = reopened.record(candidate())
        assert reopened.pending_count() == 1
        with pytest.raises(ValueError, match="conflicting duplicate"):
            reopened.record(candidate(close=100.5))

    assert original.created is True
    assert duplicate.created is False
    assert replay.created is False
    assert original.event.event_id == replay.event.event_id


def test_queue_overflow_is_explicit_and_does_not_drop_or_replace_events(tmp_path):
    with RadarBarEventLedger(tmp_path / "bounded.sqlite", max_pending=1) as ledger:
        ledger.record(candidate())
        with pytest.raises(EventQueueFull):
            ledger.record(candidate(symbol="US.NVDA"))
        assert ledger.pending_count() == 1
        assert ledger.get(candidate().idempotency_key).payload["symbol"] == "US.AMD"


def test_wake_claim_is_leased_and_recoverable_with_same_downstream_idempotency_key(tmp_path):
    with RadarBarEventLedger(tmp_path / "leases.sqlite", max_pending=3) as ledger:
        saved = ledger.record(candidate())
        first = ledger.claim_next(worker_id="worker-A", now=T0 + timedelta(minutes=1), lease_seconds=30)
        blocked = ledger.claim_next(worker_id="worker-B", now=T0 + timedelta(minutes=1), lease_seconds=30)
        recovered = ledger.claim_next(
            worker_id="worker-B", now=T0 + timedelta(minutes=2), lease_seconds=30
        )

    assert saved.event.idempotency_key == first.event.idempotency_key
    assert blocked is None
    assert recovered.event.idempotency_key == first.event.idempotency_key
    assert recovered.lease_token != first.lease_token
    assert recovered.attempt == 2


def test_ack_requires_current_lease_owner_and_is_terminal(tmp_path):
    with RadarBarEventLedger(tmp_path / "ack.sqlite", max_pending=3) as ledger:
        ledger.record(candidate())
        claimed = ledger.claim_next(worker_id="worker-A", now=T0 + timedelta(minutes=1), lease_seconds=30)
        with pytest.raises(PermissionError):
            ledger.acknowledge(claimed.event.idempotency_key, lease_token="stale-token", receipt_id="wake-1", now=T0 + timedelta(minutes=1, seconds=1))
        ledger.acknowledge(claimed.event.idempotency_key, lease_token=claimed.lease_token, receipt_id="wake-1", now=T0 + timedelta(minutes=1, seconds=1))
        assert ledger.claim_next(worker_id="worker-B", now=T0 + timedelta(minutes=2), lease_seconds=30) is None
        assert ledger.get(claimed.event.idempotency_key).status == "ACKNOWLEDGED"


def test_expired_final_attempt_moves_to_dead_letter_instead_of_dropping_silently(tmp_path):
    with RadarBarEventLedger(tmp_path / "dead-letter.sqlite", max_pending=2, max_attempts=1) as ledger:
        ledger.record(candidate())
        first = ledger.claim_next(worker_id="worker-A", now=T0 + timedelta(minutes=1), lease_seconds=5)
        assert first is not None
        assert ledger.claim_next(
            worker_id="worker-B", now=T0 + timedelta(minutes=2), lease_seconds=5
        ) is None
        item = ledger.get(first.event.idempotency_key)
        assert ledger.dead_letter_count() == 1

    assert item.status == "DEAD_LETTER"
    assert item.attempts == 1


def test_two_ledger_instances_cannot_claim_the_same_wake_concurrently(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "concurrent.sqlite"
    first = RadarBarEventLedger(path, max_pending=2)
    second = RadarBarEventLedger(path, max_pending=2)
    try:
        first.record(candidate())
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(first.claim_next, worker_id="worker-A", now=T0 + timedelta(minutes=1)),
                pool.submit(second.claim_next, worker_id="worker-B", now=T0 + timedelta(minutes=1)),
            ]
            claims = [future.result() for future in futures]
        assert sum(claim is not None for claim in claims) == 1
    finally:
        first.close()
        second.close()


def test_retry_release_is_bounded_and_dead_letters_after_final_attempt(tmp_path):
    with RadarBarEventLedger(tmp_path / "retry.sqlite", max_pending=2, max_attempts=2) as ledger:
        ledger.record(candidate())
        first = ledger.claim_next(worker_id="worker-A", now=T0 + timedelta(minutes=1))
        assert first is not None
        pending = ledger.release_for_retry(
            first.event.idempotency_key, lease_token=first.lease_token, now=T0 + timedelta(minutes=1, seconds=1)
        )
        assert pending.status == "PENDING"
        second = ledger.claim_next(worker_id="worker-A", now=T0 + timedelta(minutes=2))
        assert second is not None and second.attempt == 2
        dead = ledger.release_for_retry(
            second.event.idempotency_key, lease_token=second.lease_token, now=T0 + timedelta(minutes=2, seconds=1)
        )
        assert dead.status == "DEAD_LETTER"
        assert ledger.dead_letter_count() == 1
