import json

import pytest

from src.services.stock_radar_v2.observation_ledger import (
    LatencyTrace,
    Observation,
    ObservationCaptureWriter,
    SourceEventAtQuality,
    observation_from_capture_record,
    observation_capture_record,
    serialize_observation_capture,
)
from src.services.strategy_lab.persisted_observation_replay import read_persisted_observations


def test_capture_serialization_and_replay_round_trip(tmp_path):
    path = tmp_path / "capture.jsonl"
    item = Observation("o", "DETECTED", universe_snapshot_id="u", opportunity_id="op")
    writer = ObservationCaptureWriter(path)
    record = writer.append(item, source_type="INTEGRATION_CAPTURED_REPLAY", market="US", instrument="ABC")
    assert serialize_observation_capture(record) == serialize_observation_capture(record)
    assert tuple(read_persisted_observations(path)) == (item,)
    assert observation_from_capture_record(record) == item


def test_capture_is_append_only_and_duplicate_is_idempotent(tmp_path):
    path = tmp_path / "capture.jsonl"
    item = Observation("o", "DETECTED")
    writer = ObservationCaptureWriter(path)
    writer.append(item, source_type="CAPTURE_PIPELINE_VALIDATION")
    writer.append(item, source_type="CAPTURE_PIPELINE_VALIDATION")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_conflicting_duplicate_fails_loud(tmp_path):
    path = tmp_path / "capture.jsonl"
    item = Observation("o", "DETECTED")
    writer = ObservationCaptureWriter(path)
    writer.append(item, source_type="CAPTURE_PIPELINE_VALIDATION")
    with pytest.raises(ValueError, match="conflicting observation"):
        writer.append(Observation("o", "BLOCKED"), source_type="CAPTURE_PIPELINE_VALIDATION")


def test_schema_and_timestamp_quality_fail_closed():
    item = Observation("o", "UNKNOWN", latency=LatencyTrace())
    record = observation_capture_record(item, source_type="CAPTURE_PIPELINE_VALIDATION")
    assert record["timestamps"]["source_event_at"] is None
    assert record["timestamps"]["source_event_at_quality"] == SourceEventAtQuality.UNKNOWN.value
    with pytest.raises(ValueError, match="unsupported observation capture"):
        serialize_observation_capture({"record_type": "observation_capture", "schema_version": "v0"})


def test_outcome_enrichment_does_not_mutate_decision_record(tmp_path):
    path = tmp_path / "capture.jsonl"
    item = Observation("o", "DETECTED", canonical_permission="UNKNOWN", opportunity_id="op")
    writer = ObservationCaptureWriter(path)
    writer.append(item, source_type="CAPTURE_PIPELINE_VALIDATION")
    writer.append_outcome("o", later_outcome_label="WIN", censored=False, mfe=4, mae=1)
    records = path.read_text(encoding="utf-8").splitlines()
    assert len(records) == 2
    decision = json.loads(records[0])
    outcome = json.loads(records[1])
    assert decision["canonical_permission"] == "UNKNOWN"
    assert outcome["record_type"] == "outcome_enrichment"
    assert tuple(read_persisted_observations(path)) == (item,)


def test_conflicting_outcome_enrichment_fails_loud(tmp_path):
    path = tmp_path / "capture.jsonl"
    writer = ObservationCaptureWriter(path)
    writer.append(Observation("o", "DETECTED"), source_type="CAPTURE_PIPELINE_VALIDATION")
    writer.append_outcome("o", later_outcome_label="WIN")
    with pytest.raises(ValueError, match="conflicting outcome"):
        writer.append_outcome("o", later_outcome_label="LOSS")
