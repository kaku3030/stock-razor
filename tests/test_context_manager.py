import json
from datetime import datetime, timezone

import pytest

from src.services.context_manager import ContextManagerError, ContextManagerStore


def _clock():
    return datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def test_records_compact_state_and_append_only_event(tmp_path):
    store = ContextManagerStore(tmp_path / "current.json", clock=_clock)
    result = store.record(
        event_id="ci-1",
        event_type="ci_passed",
        source="ci",
        source_ref="run/123",
        payload={"head": "abc", "api_key": "secret-value", "checks": ["backend"]},
    )
    assert result == {"status": "RECORDED", "event_id": "ci-1", "version": 1}
    current = store.read()
    assert current["status"] == "ACTIVE"
    assert current["state"]["api_key"] == "[REDACTED]"
    assert current["safety"]["live_trade"] is False
    assert len((tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_idempotency_and_conflict_fail_closed(tmp_path):
    store = ContextManagerStore(tmp_path / "current.json", clock=_clock)
    kwargs = {"event_id": "deploy-1", "event_type": "deployment_passed", "source": "deployment", "payload": {"sha": "a"}}
    store.record(**kwargs)
    assert store.record(**kwargs)["status"] == "DUPLICATE"
    with pytest.raises(ContextManagerError):
        store.record(**{**kwargs, "payload": {"sha": "b"}})
    assert len((tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_expiry_and_failure_are_not_passes(tmp_path):
    store = ContextManagerStore(tmp_path / "current.json", clock=_clock)
    store.record(event_id="radar-1", event_type="radar_failed", source="radar", payload={"reason": "timeout"}, ttl_seconds=1)
    assert store.read()["status"] == "BLOCKED"

    times = iter((_clock(), _clock().replace(second=2)))
    expired_store = ContextManagerStore(tmp_path / "expired.json", clock=lambda: next(times))
    expired_store.record(event_id="x", event_type="engine_progress", source="engineering", payload={}, ttl_seconds=1)
    assert expired_store.read()["status"] == "EXPIRED"


def test_corrupt_log_blocks_read(tmp_path):
    state = tmp_path / "current.json"
    events = tmp_path / "events.jsonl"
    store = ContextManagerStore(state, events, clock=_clock)
    store.record(event_id="x", event_type="engine_progress", source="engineering", payload={})
    events.write_text(events.read_text(encoding="utf-8") + "not-json\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        store._read_events()
    assert store.read()["status"] == "BLOCKED"
