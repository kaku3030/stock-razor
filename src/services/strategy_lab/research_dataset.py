"""Frozen, replayable research data capsules for the validation harness.

This is a research-data boundary, not a provider runtime.  It stores no raw
provider credentials and does not fetch market data.  A capsule commits the
source/adapter identity and hashes of raw events before a rule experiment is
allowed to use the dataset.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .temporal_contract import canonical_utc_datetime, canonical_utc_text


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


class LateEventPolicy(str, Enum):
    RECOMPUTE_SHADOW = "recompute_shadow"
    DROP = "drop"


@dataclass(frozen=True)
class ResearchDataEvent:
    event_id: str
    source_event_id: str
    content_hash: str
    effective_at: datetime
    available_at: datetime
    observed_at: datetime
    original_position: int

    def __post_init__(self) -> None:
        for field in ("event_id", "source_event_id", "content_hash"):
            object.__setattr__(self, field, _text(field, getattr(self, field)))
        if isinstance(self.original_position, bool) or not isinstance(self.original_position, int) or self.original_position < 0:
            raise ValueError("original_position must be a non-negative int")
        for field in ("effective_at", "available_at", "observed_at"):
            object.__setattr__(self, field, canonical_utc_datetime(getattr(self, field)))

    @property
    def replay_key(self) -> tuple[datetime, str, int]:
        return (self.observed_at, self.event_id, self.original_position)


@dataclass(frozen=True)
class ResearchDatasetCapsule:
    dataset_id: str
    dataset_version: str
    source_id: str
    adapter_version: str
    late_event_policy: LateEventPolicy
    events: tuple[ResearchDataEvent, ...]

    def __post_init__(self) -> None:
        for field in ("dataset_id", "dataset_version", "source_id", "adapter_version"):
            object.__setattr__(self, field, _text(field, getattr(self, field)))
        if not isinstance(self.late_event_policy, LateEventPolicy):
            raise ValueError("late_event_policy must be LateEventPolicy")
        if not isinstance(self.events, tuple) or not self.events or not all(isinstance(item, ResearchDataEvent) for item in self.events):
            raise ValueError("events must be a non-empty tuple of ResearchDataEvent")
        ids = [item.event_id for item in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("event_id values must be unique")
        object.__setattr__(self, "events", tuple(sorted(self.events, key=lambda item: item.replay_key)))

    @property
    def fingerprint(self) -> str:
        payload = {"schema": "research-dataset-capsule-v0.1", "dataset_id": self.dataset_id,
                   "dataset_version": self.dataset_version, "source_id": self.source_id,
                   "adapter_version": self.adapter_version, "late_event_policy": self.late_event_policy.value,
                   "events": [{"event_id": item.event_id, "source_event_id": item.source_event_id,
                               "content_hash": item.content_hash, "effective_at": canonical_utc_text(item.effective_at),
                               "available_at": canonical_utc_text(item.available_at),
                               "observed_at": canonical_utc_text(item.observed_at), "original_position": item.original_position}
                              for item in self.events]}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
