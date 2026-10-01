from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.services.strategy_lab.replay_contract import EventRecord

UTC = timezone.utc
NOW = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)


def _event() -> EventRecord:
    return EventRecord(
        event_id="event-1",
        event_type="TEST_EVENT",
        entity_id="SSE:600000",
        theme_id=None,
        occurred_at=NOW,
        event_time=NOW,
        published_at=NOW,
        available_at=NOW,
        observed_at=NOW,
        created_at=NOW,
        source_id="fixture://strategy-lab/replay-a2-integrity",
        payload={"value": 1.0},
        trace_id="trace-integrity-1",
    )


def test_stale_supplied_checksum_cannot_mask_payload_tamper():
    event = _event()
    with pytest.raises(ValueError, match="checksum does not match canonical event content"):
        replace(event, payload={"value": 999.0}, checksum=event.checksum)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", " event-1"),
        ("event_type", "TEST_EVENT "),
        ("source_id", " fixture"),
        ("trace_id", "trace "),
    ],
)
def test_audit_identity_strings_must_be_canonical_trimmed(field, value):
    kwargs = {
        "event_id": "event-1",
        "event_type": "TEST_EVENT",
        "entity_id": "SSE:600000",
        "theme_id": None,
        "occurred_at": NOW,
        "event_time": NOW,
        "published_at": NOW,
        "available_at": NOW,
        "observed_at": NOW,
        "created_at": NOW,
        "source_id": "fixture",
        "payload": {},
        "trace_id": "trace-integrity-1",
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=f"{field} must be a non-empty trimmed string"):
        EventRecord(**kwargs)
