"""Audit-critical replay contracts for Strategy Lab shadow research.

Foundation/Data-Reliability scope only.  These objects are deliberately
isolated from live routing, notifications, broker execution, LLM/KG work and
production promotion.  Passing tests here is evidence about replay integrity;
it does not grant SHADOW_ACTIVE, CORE, LIVE or trading authority.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from typing import Any, Callable

UTC = timezone.utc
UNKNOWN = "__UNKNOWN__"


class FrozenDict(Mapping[str, Any]):
    """Recursively immutable mapping for audit-critical payloads."""

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self._data = {str(key): deep_freeze(value) for key, value in (data or {}).items()}

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __deepcopy__(self, memo):
        return self


def deep_freeze(value: Any) -> Any:
    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, Mapping):
        return FrozenDict(value)
    if isinstance(value, list):
        return tuple(deep_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(deep_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(deep_freeze(item) for item in value)
    return value


def aware_utc(value: datetime | None, name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def canonicalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {key: canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(canonicalize(item) for item in value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite floats are not canonicalizable")
        return repr(value)
    return value


def stable_hash(value: Any) -> str:
    payload = json.dumps(
        canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


@dataclass(frozen=True)
class SourceAuthorityResolution:
    """Read-only identity snapshot returned by a canonical repository authority."""

    source_token: str
    endpoint_id: str
    market: str
    adapter_id: str
    upstream_lineage_id: str
    authority_ref: str

    def __post_init__(self) -> None:
        for name in (
            "source_token",
            "endpoint_id",
            "market",
            "adapter_id",
            "upstream_lineage_id",
            "authority_ref",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a non-empty trimmed string")


SourceAuthorityResolver = Callable[[str, str, str], SourceAuthorityResolution | None]


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    event_type: str
    entity_id: str | None
    theme_id: str | None
    occurred_at: datetime
    event_time: datetime
    published_at: datetime | None
    available_at: datetime | None
    observed_at: datetime
    created_at: datetime
    source_id: str
    payload: Mapping[str, Any]
    parent_event_ids: tuple[str, ...] = ()
    revision_id: str | None = None
    supersedes_id: str | None = None
    trace_id: str = "trace-replay-sandbox"
    checksum: str = ""
    sequence_no: int | None = None
    source_kind: str = "SYNTHETIC"
    source_token: str | None = None
    endpoint_id: str | None = None
    market: str | None = None
    source_authority_ref: str | None = None
    source_adapter_id: str | None = None
    source_upstream_lineage_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "event_type", "source_id", "trace_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a non-empty trimmed string")
        if self.source_kind not in {
            "SYNTHETIC",
            "PROVIDER",
            "ENGINE_DERIVED",
            "OFFICIAL",
            "RESEARCH",
        }:
            raise ValueError("unsupported source_kind")
        for name in ("occurred_at", "event_time", "observed_at", "created_at"):
            object.__setattr__(self, name, aware_utc(getattr(self, name), name))
        for name in ("published_at", "available_at"):
            object.__setattr__(self, name, aware_utc(getattr(self, name), name))
        if self.available_at is not None and self.observed_at < self.available_at:
            raise ValueError("observed_at cannot precede available_at")
        if self.created_at < self.observed_at:
            raise ValueError("created_at cannot precede observed_at")
        object.__setattr__(self, "payload", deep_freeze(self.payload))
        expected_checksum = stable_hash(self._checksum_payload())
        if self.checksum:
            if self.checksum != expected_checksum:
                raise ValueError("checksum does not match canonical event content")
        else:
            object.__setattr__(self, "checksum", expected_checksum)

    def _checksum_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("checksum", None)
        payload.pop("sequence_no", None)
        return payload

    def canonical_payload(self) -> dict[str, Any]:
        return self._checksum_payload() | {"checksum": self.checksum}


@dataclass(frozen=True)
class PatternInstance:
    pattern_id: str
    version: str
    pattern_instance_id: str
    partition_key: str
    trigger_clock: datetime
    input_event_ids: tuple[str, ...]
    severity: str
    dedup_key: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "trigger_clock", aware_utc(self.trigger_clock, "trigger_clock"))
        object.__setattr__(self, "payload", deep_freeze(self.payload))

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    decision_clock: datetime
    accepted_event_ids: tuple[str, ...]
    pattern_instances: tuple[PatternInstance, ...]
    rule_version: str
    data_version: str
    audit_status: str
    unknown_bitmap: tuple[tuple[str, tuple[str, ...]], ...]
    canonical_hash: str


@dataclass(frozen=True)
class ReplayResult:
    snapshot: Snapshot
    duplicate_count: int
    late_count: int
    rejected_count: int
    late_dropped_count: int
    derived_replay_mismatch_count: int
    side_effect_count: int


class InMemoryEventStore:
    """Append-only in-memory store used only by the replay sandbox."""

    def __init__(
        self,
        *,
        source_authority_resolver: SourceAuthorityResolver | None = None,
        late_event_policy: str = "RECOMPUTE_SHADOW",
    ) -> None:
        if late_event_policy not in {"RECOMPUTE_SHADOW", "DROP"}:
            raise ValueError("late_event_policy must be RECOMPUTE_SHADOW or DROP")
        self._events: list[EventRecord] = []
        self._seen_ids: set[str] = set()
        self._dropped_late_ids: set[str] = set()
        self._event_checksums: dict[str, str] = {}
        self._max_observed_at: datetime | None = None
        self._resolver = source_authority_resolver
        self.late_event_policy = late_event_policy
        self.duplicate_count = 0
        self.late_count = 0
        self.late_dropped_count = 0
        self.rejected_count = 0

    def append(self, event: EventRecord) -> str:
        admitted = self._admit_source(event)
        if admitted is None:
            self.rejected_count += 1
            return "REJECTED_SOURCE_AUTHORITY"
        event = admitted

        prior_checksum = self._event_checksums.get(event.event_id)
        if prior_checksum is not None:
            if prior_checksum != event.checksum:
                raise ValueError("event_id collision with conflicting checksum")
            self.duplicate_count += 1
            return "DUPLICATE"

        is_late = self._max_observed_at is not None and event.observed_at < self._max_observed_at
        if is_late:
            self.late_count += 1
            if self.late_event_policy == "DROP":
                self.late_dropped_count += 1
                self._dropped_late_ids.add(event.event_id)
                self._event_checksums[event.event_id] = event.checksum
                return "LATE_DROPPED"

        if self._max_observed_at is None or event.observed_at > self._max_observed_at:
            self._max_observed_at = event.observed_at
        accepted = EventRecord(**{**asdict(event), "sequence_no": len(self._events) + 1})
        self._events.append(accepted)
        self._seen_ids.add(event.event_id)
        self._event_checksums[event.event_id] = event.checksum
        return "ACCEPTED"

    def _admit_source(self, event: EventRecord) -> EventRecord | None:
        authority_fields = (
            event.source_authority_ref,
            event.source_adapter_id,
            event.source_upstream_lineage_id,
        )
        if event.source_kind != "PROVIDER":
            return None if any(authority_fields) else event
        if not event.source_token or not event.endpoint_id or not event.market or self._resolver is None:
            return None
        resolution = self._resolver(event.source_token, event.endpoint_id, event.market)
        if resolution is None:
            return None
        if (
            resolution.source_token != event.source_token
            or resolution.endpoint_id != event.endpoint_id
            or resolution.market != event.market
        ):
            return None
        admitted = asdict(event)
        admitted.update(
            source_authority_ref=resolution.authority_ref,
            source_adapter_id=resolution.adapter_id,
            source_upstream_lineage_id=resolution.upstream_lineage_id,
            checksum="",
        )
        return EventRecord(**admitted)

    def query_as_of(self, decision_clock: datetime) -> list[EventRecord]:
        clock = aware_utc(decision_clock, "decision_clock")
        return sorted(
            (event for event in self._events if event.observed_at <= clock),
            key=lambda event: (event.observed_at, event.event_id),
        )

    @property
    def events(self) -> tuple[EventRecord, ...]:
        return tuple(self._events)
