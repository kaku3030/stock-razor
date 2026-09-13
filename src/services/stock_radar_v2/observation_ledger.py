"""Append-only research observations and their latency provenance."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping


OBSERVATION_SCHEMA_VERSION = "observation-ledger-v0.1"


class SourceEventAtQuality(StrEnum):
    EXACT = "EXACT"
    DERIVED = "DERIVED"
    UNKNOWN = "UNKNOWN"


OBSERVATION_SCHEMA_VERSION = "observation-ledger-v0.1"
OBSERVATION_CAPTURE_CONTRACT_VERSION = "observation-capture-v0.1"


@dataclass(frozen=True)
class LatencyTrace:
    source_event_at: float | None = None
    source_event_at_quality: SourceEventAtQuality = SourceEventAtQuality.UNKNOWN
    data_received_at: float | None = None
    knowledge_available_at: float | None = None
    detected_at: float | None = None
    strategy_decided_at: float | None = None
    risk_decided_at: float | None = None
    execution_ready_at: float | None = None
    order_sent_at: float | None = None
    fill_at: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_event_at_quality, SourceEventAtQuality):
            raise TypeError("source_event_at_quality must be a SourceEventAtQuality")
        values = [getattr(self, name) for name in _TIMESTAMP_FIELDS]
        present = [value for value in values if value is not None]
        if any(value < 0 for value in present) or any(a > b for a, b in zip(present, present[1:])):
            raise ValueError("latency timestamps must be non-negative and monotonic")
        if self.source_event_at_quality is SourceEventAtQuality.UNKNOWN and self.source_event_at is not None:
            raise ValueError("UNKNOWN source_event_at quality requires a missing source_event_at")
        if self.source_event_at_quality is not SourceEventAtQuality.UNKNOWN and self.source_event_at is None:
            raise ValueError("EXACT or DERIVED source_event_at quality requires source_event_at")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "source_event_at_quality": self.source_event_at_quality.value}

    def system_latency(self) -> float | None:
        segments = (
            (self.data_received_at, self.knowledge_available_at),
            (self.strategy_decided_at, self.risk_decided_at),
            (self.risk_decided_at, self.execution_ready_at),
        )
        durations = [end - start for start, end in segments if start is not None and end is not None]
        return sum(durations) if durations else None

    def policy_wait(self) -> float | None:
        if self.knowledge_available_at is None or self.strategy_decided_at is None:
            return None
        return self.strategy_decided_at - self.knowledge_available_at

    def catalyst_latency(self) -> float | None:
        if self.source_event_at is None or self.detected_at is None:
            return None
        return self.detected_at - self.source_event_at


_TIMESTAMP_FIELDS = (
    "source_event_at",
    "data_received_at",
    "knowledge_available_at",
    "detected_at",
    "strategy_decided_at",
    "risk_decided_at",
    "execution_ready_at",
    "order_sent_at",
    "fill_at",
)


@dataclass(frozen=True)
class Observation:
    observation_id: str
    detector_status: str
    evidence_ids: tuple[str, ...] = ()
    strategy_gate_results: Mapping[str, str] = field(default_factory=dict)
    strategy_eligible: bool | None = None
    portfolio_admissible: bool | None = None
    portfolio_block_reasons: tuple[str, ...] = ()
    execution_feasible: bool | None = None
    execution_record_id: str | None = None
    interrupted_reason: str | None = None
    decision_available_at: float | None = None
    confirmed_at: float | None = None
    earliest_executable_at: float | None = None
    canonical_permission: str = "UNKNOWN"
    later_outcome_label: str | None = None
    censored: bool = False
    mfe: float | None = None
    mae: float | None = None
    universe_snapshot_id: str | None = None
    latency: LatencyTrace = field(default_factory=LatencyTrace)
    opportunity_id: str | None = None

    def __post_init__(self) -> None:
        known = [value for value in (self.decision_available_at, self.confirmed_at) if value is not None]
        if self.earliest_executable_at is not None and known:
            if self.earliest_executable_at < max(known):
                raise ValueError("earliest_executable_at cannot precede decision availability")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["latency"] = self.latency.to_dict()
        value["evidence_ids"] = list(self.evidence_ids)
        value["portfolio_block_reasons"] = list(self.portfolio_block_reasons)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Observation":
        required = {"observation_id", "detector_status"}
        missing = required - value.keys()
        if missing:
            raise ValueError(f"observation record missing fields: {sorted(missing)}")
        latency = value.get("latency", {})
        if not isinstance(latency, Mapping):
            raise ValueError("observation latency must be an object")
        quality = latency.get("source_event_at_quality", SourceEventAtQuality.UNKNOWN.value)
        try:
            trace = LatencyTrace(**{**latency, "source_event_at_quality": SourceEventAtQuality(quality)})
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid observation latency") from exc
        return cls(
            observation_id=str(value["observation_id"]), detector_status=str(value["detector_status"]),
            evidence_ids=tuple(value.get("evidence_ids", ())), strategy_gate_results=dict(value.get("strategy_gate_results", {})),
            strategy_eligible=value.get("strategy_eligible"), portfolio_admissible=value.get("portfolio_admissible"),
            portfolio_block_reasons=tuple(value.get("portfolio_block_reasons", ())), execution_feasible=value.get("execution_feasible"),
            execution_record_id=value.get("execution_record_id"), interrupted_reason=value.get("interrupted_reason"),
            decision_available_at=value.get("decision_available_at"), confirmed_at=value.get("confirmed_at"),
            earliest_executable_at=value.get("earliest_executable_at"), canonical_permission=str(value.get("canonical_permission", "UNKNOWN")),
            later_outcome_label=value.get("later_outcome_label"), censored=bool(value.get("censored", False)),
            mfe=value.get("mfe"), mae=value.get("mae"), universe_snapshot_id=value.get("universe_snapshot_id"),
            latency=trace, opportunity_id=value.get("opportunity_id"),
        )

    def serialize(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _capture_timestamps(observation: Observation) -> dict[str, float | None]:
    latency = observation.latency.to_dict()
    return {
        **{name: latency[name] for name in _TIMESTAMP_FIELDS},
        "source_event_at_quality": latency["source_event_at_quality"],
        "decision_available_at": observation.decision_available_at,
    }


def observation_capture_record(
    observation: Observation,
    *,
    source_type: str,
    market: str | None = None,
    instrument: str | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one generated Observation into the append-only capture contract."""
    return {
        "record_type": "observation_capture",
        "schema_version": OBSERVATION_CAPTURE_CONTRACT_VERSION,
        "observation_id": observation.observation_id,
        "source_type": source_type,
        "market": market,
        "instrument": instrument,
        "universe_snapshot_id": observation.universe_snapshot_id,
        "detector_status": observation.detector_status,
        "evidence_ids": list(observation.evidence_ids),
        "strategy_gate_results": dict(observation.strategy_gate_results),
        "strategy_eligible": observation.strategy_eligible,
        "portfolio_admissible": observation.portfolio_admissible,
        "portfolio_block_reasons": list(observation.portfolio_block_reasons),
        "execution_feasible": observation.execution_feasible,
        "canonical_permission": observation.canonical_permission,
        "timestamps": _capture_timestamps(observation),
        "later_outcome_label": observation.later_outcome_label,
        "censored": observation.censored,
        "mfe": observation.mfe,
        "mae": observation.mae,
        "opportunity_id": observation.opportunity_id,
        "provenance": dict(provenance or {}),
    }


def serialize_observation_capture(record: Mapping[str, Any]) -> str:
    if record.get("record_type") != "observation_capture" or record.get("schema_version") != OBSERVATION_CAPTURE_CONTRACT_VERSION:
        raise ValueError("unsupported observation capture schema or record type")
    if not record.get("observation_id"):
        raise ValueError("observation capture requires observation_id")
    return json.dumps(dict(record), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def observation_from_capture_record(record: Mapping[str, Any]) -> Observation:
    if record.get("record_type") != "observation_capture" or record.get("schema_version") != OBSERVATION_CAPTURE_CONTRACT_VERSION:
        raise ValueError("unsupported observation capture schema or record type")
    timestamps = record.get("timestamps")
    if not isinstance(timestamps, Mapping):
        raise ValueError("observation capture timestamps must be an object")
    latency_values = {name: timestamps.get(name) for name in _TIMESTAMP_FIELDS}
    quality = timestamps.get("source_event_at_quality", SourceEventAtQuality.UNKNOWN.value)
    latency_values["source_event_at_quality"] = SourceEventAtQuality(quality)
    return Observation(
        observation_id=str(record["observation_id"]), detector_status=str(record["detector_status"]),
        evidence_ids=tuple(record.get("evidence_ids", ())), strategy_gate_results=dict(record.get("strategy_gate_results", {})),
        strategy_eligible=record.get("strategy_eligible"), portfolio_admissible=record.get("portfolio_admissible"),
        portfolio_block_reasons=tuple(record.get("portfolio_block_reasons", ())), execution_feasible=record.get("execution_feasible"),
        decision_available_at=record.get("timestamps", {}).get("decision_available_at"),
        canonical_permission=str(record.get("canonical_permission", "UNKNOWN")), later_outcome_label=record.get("later_outcome_label"),
        censored=bool(record.get("censored", False)), mfe=record.get("mfe"), mae=record.get("mae"),
        universe_snapshot_id=record.get("universe_snapshot_id"), latency=LatencyTrace(**latency_values),
        opportunity_id=record.get("opportunity_id"),
    )


class ObservationCaptureWriter:
    """Append-only sink owned by the Observation Ledger; it never rewrites decisions."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._observations: dict[str, str] = {}
        self._outcomes: dict[str, str] = {}
        if self._path.exists():
            with self._path.open(encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    record_type = value.get("record_type")
                    key = value.get("observation_id")
                    if record_type == "observation_capture":
                        encoded = serialize_observation_capture(value)
                        if key in self._observations and self._observations[key] != encoded:
                            raise ValueError("conflicting observation capture duplicate")
                        self._observations[key] = encoded
                    elif record_type == "outcome_enrichment":
                        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                        if key in self._outcomes and self._outcomes[key] != encoded:
                            raise ValueError("conflicting outcome enrichment duplicate")
                        self._outcomes[key] = encoded
                    else:
                        raise ValueError("unsupported capture record type")

    def append(self, observation: Observation, **context: Any) -> dict[str, Any]:
        record = observation_capture_record(observation, **context)
        encoded = serialize_observation_capture(record)
        previous = self._observations.get(observation.observation_id)
        if previous is not None:
            if previous != encoded:
                raise ValueError("conflicting observation capture duplicate")
            return record
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded + "\n")
        self._observations[observation.observation_id] = encoded
        return record

    def append_outcome(self, observation_id: str, **outcome: Any) -> dict[str, Any]:
        record = {"record_type": "outcome_enrichment", "schema_version": OBSERVATION_CAPTURE_CONTRACT_VERSION,
                  "observation_id": observation_id, **outcome}
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        previous = self._outcomes.get(observation_id)
        if previous is not None:
            if previous != encoded:
                raise ValueError("conflicting outcome enrichment duplicate")
            return record
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded + "\n")
        self._outcomes[observation_id] = encoded
        return record

def serialize_observation_record(observation: Observation) -> str:
    """Return one versioned, deterministic append-only JSONL record."""
    return json.dumps({"record_type": "observation", "schema_version": OBSERVATION_SCHEMA_VERSION,
                       "observation": observation.to_dict()}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def deserialize_observation_record(line: str) -> Observation:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid observation JSONL record") from exc
    if value.get("schema_version") != OBSERVATION_SCHEMA_VERSION or value.get("record_type") != "observation":
        raise ValueError("unsupported observation schema or record type")
    payload = value.get("observation")
    if not isinstance(payload, Mapping):
        raise ValueError("observation record payload must be an object")
    return Observation.from_dict(payload)


class ObservationLedger:
    """Small append-only ledger; identical replay keys are idempotent."""

    def __init__(self) -> None:
        self._records: dict[str, Observation] = {}

    def append(self, observation: Observation) -> Observation:
        previous = self._records.get(observation.observation_id)
        if previous is not None and previous.serialize() != observation.serialize():
            raise ValueError("observation replay conflicts with existing record")
        self._records.setdefault(observation.observation_id, observation)
        return self._records[observation.observation_id]

    def records(self) -> tuple[Observation, ...]:
        return tuple(self._records.values())
