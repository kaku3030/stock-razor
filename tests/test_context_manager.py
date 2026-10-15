import json
from datetime import datetime, timezone

import pytest

from src.services.context_manager import ContextManagerError, ContextManagerStore


def _overlapping_context_writer(root, barrier, worker):
    import time
    from pathlib import Path

    class SlowReadStore(ContextManagerStore):
        def _read_events(self):
            events = super()._read_events()
            time.sleep(0.05)
            return events

    store = SlowReadStore(Path(root) / "current.json")
    barrier.wait(timeout=10)
    for i in range(3):
        store.record(event_id=f"worker:{worker}:{i}", event_type="ci_success",
                     source="ci", payload={"worker": worker, "index": i})


def test_overlapping_processes_serialize_version_allocation_and_state(tmp_path):
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    processes = [context.Process(target=_overlapping_context_writer,
                 args=(str(tmp_path), barrier, i)) for i in range(2)]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=20)
        assert [process.exitcode for process in processes] == [0, 0]
        events = [json.loads(row) for row in (tmp_path / "events.jsonl").read_text().splitlines()]
        assert [row["version"] for row in events] == list(range(1, 7))
        assert len({row["event_id"] for row in events}) == 6
        current = ContextManagerStore(tmp_path / "current.json").read()
        assert current["status"] == "ACTIVE"
        assert current["safety"]["live_trade"] is False
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)


def test_explicit_sequence_repair_preserves_all_evidence_and_private_backup(tmp_path):
    import hashlib

    store = ContextManagerStore(tmp_path / "current.json", clock=_clock)
    for i in range(2):
        store.record(event_id=f"ci:{i}", event_type="ci_failure", source="ci", payload={"i": i})
    events = store._read_events()
    events[1]["version"] = 1
    original = "".join(json.dumps(item) + "\n" for item in events).encode()
    store.events_path.write_bytes(original)
    digest = hashlib.sha256(original).hexdigest()
    assert store.read()["status"] == "BLOCKED"
    result = store.repair_version_sequence(expected_sha256=digest)
    assert result["status"] == "REPAIRED" and result["event_count"] == 2
    backup = next(tmp_path.glob("events.jsonl.before-sequence-repair-*"))
    assert backup.read_bytes() == original
    import os
    if os.name != "nt":
        assert backup.stat().st_mode & 0o777 == 0o600
    repaired = store._read_events()
    assert [e["version"] for e in repaired] == [1, 2]
    assert [{k: v for k, v in e.items() if k != "version"} for e in repaired] == [
        {k: v for k, v in e.items() if k != "version"} for e in events]
    current = store.read()
    assert current["domains"]["ci"]["status"] == "BLOCKED"
    assert current["safety"]["live_trade"] is False
    assert current["domains"]["ci"]["acceptance"] == "UNVERIFIED"
    store.record(event_id="next", event_type="ci_success", source="ci", payload={})
    assert store._read_events()[-1]["version"] == 3


@pytest.mark.parametrize("damage", ["digest", "payload", "gap", "duplicate_id"])
def test_sequence_repair_refuses_other_damage_without_touching_log(tmp_path, damage):
    import hashlib

    store = ContextManagerStore(tmp_path / "current.json", clock=_clock)
    for i in range(2):
        store.record(event_id=f"ci:{i}", event_type="ci_success", source="ci", payload={"i": i})
    events = store._read_events()
    events[1]["version"] = 1
    if damage == "payload":
        events[1]["payload"]["i"] = 99
    elif damage == "gap":
        events[1]["version"] = 3
    elif damage == "duplicate_id":
        events[1]["event_id"] = events[0]["event_id"]
    original = "".join(json.dumps(e) + "\n" for e in events).encode()
    store.events_path.write_bytes(original)
    digest = "0" * 64 if damage == "digest" else hashlib.sha256(original).hexdigest()
    with pytest.raises(ContextManagerError):
        store.repair_version_sequence(expected_sha256=digest)
    assert store.events_path.read_bytes() == original
    assert not list(tmp_path.glob("events.jsonl.before-sequence-repair-*"))


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
def test_recovery_snapshot_keeps_each_domain_with_provenance_and_ttl(tmp_path):
    store = ContextManagerStore(tmp_path / "current.json", clock=_clock)
    store.record(
        event_id="pr-1", event_type="pr_merged", source="engineering",
        payload={"number": 701, "merge_sha": "abc"}, source_ref="github/pr/701",
    )
    store.record(
        event_id="ci-1", event_type="ci_failed", source="ci",
        payload={"workflow": "backend-gate", "sha": "abc"}, source_ref="run/1",
    )

    domains = store.read()["domains"]
    assert domains["pr"]["last_known"]["number"] == 701
    assert domains["pr"]["provenance"]["source_ref"] == "github/pr/701"
    assert domains["pr"]["acceptance"] == "UNVERIFIED"
    assert domains["ci"]["status"] == "BLOCKED"
    assert domains["deploy"]["status"] == "UNKNOWN"
    assert domains["ci"]["ttl"]["expired"] is False


def test_sequence_repair_retry_rebuilds_state_without_new_backup(tmp_path):
    import hashlib
    store = ContextManagerStore(tmp_path / "current.json", clock=_clock)
    store.record(event_id="valid", event_type="ci_failed", source="ci", payload={})
    original = store.events_path.read_bytes()
    store.state_path.write_text("broken")
    result = store.repair_version_sequence(expected_sha256=hashlib.sha256(original).hexdigest())
    assert result["status"] == "STATE_REBUILT" and not result["backup_created"]
    assert store.events_path.read_bytes() == original
    assert not list(tmp_path.glob("events.jsonl.before-sequence-repair-*"))
    assert store.read()["domains"]["ci"]["status"] == "BLOCKED"
