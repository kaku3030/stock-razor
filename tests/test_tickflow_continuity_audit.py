"""Acceptance tests for offline TickFlow continuity evidence."""
from datetime import datetime, timedelta, timezone

import pytest

from src.services.tickflow_continuity_audit import (
    TickflowContinuityStatus,
    TickflowObservation,
    audit_tickflow_continuity,
)


NOW = datetime(2026, 10, 10, 13, 0, tzinfo=timezone.utc)


def obs(sequence, seconds):
    return TickflowObservation(sequence, NOW - timedelta(seconds=seconds))


def test_contiguous_fresh_sequence_passes():
    result = audit_tickflow_continuity(
        (obs(10, 3), obs(11, 2), obs(12, 1)),
        now_utc=NOW,
        max_age_seconds=5,
    )
    assert result.status is TickflowContinuityStatus.PASS
    assert result.reasons == ()


@pytest.mark.parametrize(
    ("items", "reason"),
    [
        ((obs(10, 3), obs(12, 1)), "SEQUENCE_GAP"),
        ((obs(10, 3), obs(10, 1)), "SEQUENCE_DUPLICATE"),
        ((obs(11, 1), obs(10, 2)), "SEQUENCE_NOT_MONOTONIC"),
        ((obs(None, 2), obs(11, 1)), "SEQUENCE_MISSING"),
    ],
)
def test_sequence_failures_are_fail_closed(items, reason):
    result = audit_tickflow_continuity(
        items, now_utc=NOW, max_age_seconds=5
    )
    assert result.status is TickflowContinuityStatus.BLOCKED
    assert reason in result.reasons


def test_stale_and_future_timestamps_are_blocked():
    stale = audit_tickflow_continuity(
        (obs(10, 10),), now_utc=NOW, max_age_seconds=5
    )
    future = audit_tickflow_continuity(
        (TickflowObservation(10, NOW + timedelta(seconds=1)),),
        now_utc=NOW,
        max_age_seconds=5,
    )
    assert stale.reasons == ("LATEST_OBSERVATION_STALE",)
    assert future.reasons == ("FUTURE_TIMESTAMP",)


def test_empty_observation_set_is_blocked():
    result = audit_tickflow_continuity(
        (), now_utc=NOW, max_age_seconds=5
    )
    assert result.status is TickflowContinuityStatus.BLOCKED
    assert result.reasons == ("NO_OBSERVATIONS",)
