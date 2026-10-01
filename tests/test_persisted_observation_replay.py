import json
from pathlib import Path

import pytest

from src.services.stock_radar_v2.observation_ledger import (
    Observation, ObservationLedger, deserialize_observation_record, serialize_observation_record,
)
from scripts.strategy_lab_persisted_replay import build_persisted_baseline
from src.services.strategy_lab.persisted_observation_replay import load_replay_inputs, read_persisted_observations
from src.services.strategy_lab.opportunity_cost import MissReason, OpportunityTruth, TruthStatus, evaluate


def test_versioned_serializer_is_deterministic_and_round_trips():
    item = Observation("o", "DETECTED", opportunity_id="op")
    encoded = serialize_observation_record(item)
    assert encoded == serialize_observation_record(item)
    assert deserialize_observation_record(encoded) == item


def test_schema_version_fails_loud():
    with pytest.raises(ValueError, match="unsupported observation schema"):
        deserialize_observation_record('{"record_type":"observation","schema_version":"v0"}')


def test_truth_schema_version_fails_loud(tmp_path):
    (tmp_path / "observations.jsonl").write_text("", encoding="utf-8")
    path = tmp_path / "truths.jsonl"
    path.write_text('{"schema_version":"truth-v0"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported truth schema"):
        load_replay_inputs(tmp_path / "observations.jsonl", path)


def test_duplicate_persisted_replay_is_idempotent(tmp_path):
    item = Observation("o", "DETECTED", opportunity_id="op")
    path = tmp_path / "observations.jsonl"
    path.write_text((serialize_observation_record(item) + "\n") * 2, encoding="utf-8")
    assert tuple(read_persisted_observations(path)) == (item,)
    ledger = ObservationLedger()
    assert ledger.append(item) is ledger.append(item)


def test_stable_id_only_and_ambiguous_join_is_unknown():
    truth = OpportunityTruth("op", "u", "truth-v0.1", 1, 2, 1.5, TruthStatus.OPPORTUNITY, False)
    observations = [Observation("a", "DETECTED", opportunity_id="op"), Observation("b", "DETECTED", opportunity_id="op"), Observation("guess", "DETECTED")]
    record = evaluate(observations, [truth])[0]
    assert record.observation_id is None and record.miss_reason is MissReason.UNKNOWN


def test_future_labels_do_not_mutate_observation_and_missing_time_is_unknown(tmp_path):
    item = Observation("o", "DETECTED", opportunity_id="op", canonical_permission="UNKNOWN")
    observation_path = tmp_path / "observations.jsonl"
    observation_path.write_text(serialize_observation_record(item) + "\n", encoding="utf-8")
    truth_path = tmp_path / "truths.jsonl"
    truth_path.write_text(json.dumps({"schema_version": "opportunity-truth-v0.1", "opportunity_id": "op", "universe_snapshot_id": "u", "definition_version": "truth-v0.1", "horizon": 1, "label_available_at": 2, "outcome_end_at": 1.5, "status": "OPPORTUNITY", "censored": False, "mfe": 3}, sort_keys=True) + "\n", encoding="utf-8")
    observations, truths = load_replay_inputs(observation_path, truth_path)
    assert observations[0] == item and observations[0].later_outcome_label is None
    assert truths[0].mfe == 3


def test_committed_persisted_artifact_is_recomputable():
    root = Path(__file__).resolve().parents[1]
    expected = json.loads((root / "research/artifacts/persisted-replay-calibration-v0.1.json").read_text(encoding="utf-8"))
    assert build_persisted_baseline(root) == expected
