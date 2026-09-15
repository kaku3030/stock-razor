"""Research-only reader joining persisted observations to ex-post truth labels."""

from __future__ import annotations

import json
from pathlib import Path

from src.services.stock_radar_v2.observation_ledger import ObservationLedger, deserialize_observation_record
from src.services.strategy_lab.opportunity_cost import OpportunityTruth, TruthStatus


def read_persisted_observations(path: Path):
    """Read canonical Observation Ledger JSONL without mutating production state."""
    ledger = ObservationLedger()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                ledger.append(deserialize_observation_record(line))
    yield from (item for item in ledger.records() if item.opportunity_id is not None)


def read_truth_labels(path: Path) -> tuple[OpportunityTruth, ...]:
    labels = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                value = json.loads(line)
                if value.get("schema_version") != "opportunity-truth-v0.1":
                    raise ValueError("unsupported truth schema")
                payload = dict(value)
                payload.pop("schema_version", None)
                payload["status"] = TruthStatus(payload["status"])
                labels.append(OpportunityTruth(**payload))
    return tuple(labels)


def load_replay_inputs(observation_path: Path, truth_path: Path):
    return tuple(read_persisted_observations(observation_path)), read_truth_labels(truth_path)
