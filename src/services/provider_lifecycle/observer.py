"""Runtime provider observer with field-level evidence provenance.

This module is intentionally narrower than provider health assessment and data
admission. It records what was observed, when, and from where; it does not make
fallback, Radar-admission, alert, spend, or execution decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from .contract import ProviderLifecycleRecord
from .registry import DEFAULT_PROVIDER_REGISTRY, ProviderDefinition


_STATIC_FIELDS = frozenset({
    "provider_id",
    "role",
    "market_scope",
    "decision_criticality",
    "fallback_provider",
})

_RUNTIME_FIELDS = frozenset(ProviderLifecycleRecord.__dataclass_fields__) - _STATIC_FIELDS


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string when provided")
    if value != value.strip():
        raise ValueError(f"{field_name} must not contain outer whitespace")
    return value


@dataclass(frozen=True)
class EvidenceProvenance:
    observed_at: datetime
    source: str
    runtime_id: str | None = None
    repo_sha: str | None = None
    error_code: str | None = None
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")
        _optional_text(self.source, "source")
        for field_name in ("runtime_id", "repo_sha", "error_code", "evidence_id"):
            _optional_text(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class ObservedProviderValue:
    value: object
    provenance: EvidenceProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, EvidenceProvenance):
            raise TypeError("provenance must be EvidenceProvenance")


@dataclass(frozen=True)
class ProviderRuntimeObservation:
    provider_id: str
    fields: Mapping[str, ObservedProviderValue]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise ValueError("provider_id is required")
        if self.provider_id != self.provider_id.strip():
            raise ValueError("provider_id must not contain outer whitespace")
        if not self.fields:
            raise ValueError("fields must not be empty")

        invalid_keys = [name for name in self.fields if not isinstance(name, str)]
        if invalid_keys:
            raise ValueError("runtime evidence field names must be strings")

        unknown = sorted(set(self.fields) - _RUNTIME_FIELDS)
        if unknown:
            raise ValueError(
                "unsupported runtime evidence field(s): " + ", ".join(unknown)
            )

        invalid_values = [
            name
            for name, observed in self.fields.items()
            if not isinstance(observed, ObservedProviderValue)
        ]
        if invalid_values:
            raise TypeError(
                "runtime evidence values must be ObservedProviderValue: "
                + ", ".join(sorted(invalid_values))
            )

        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))


@dataclass(frozen=True)
class RuntimeProviderSnapshot:
    record: ProviderLifecycleRecord
    field_provenance: Mapping[str, EvidenceProvenance]
    observed_at: datetime
    evidence_count: int

    def provenance_for(self, field_name: str) -> EvidenceProvenance | None:
        return self.field_provenance.get(field_name)


class EvidenceConflictError(ValueError):
    """Raised when equal-time evidence disagrees and ordering cannot resolve it."""


class ProviderRuntimeObserver:
    """In-memory, fail-closed collector for provider lifecycle evidence.

    Evidence is merged independently per lifecycle field. Newer evidence wins;
    older evidence cannot roll a field backward. Equal-time conflicting values
    are rejected rather than resolved by source preference.
    """

    def __init__(
        self,
        registry: Mapping[str, ProviderDefinition] = DEFAULT_PROVIDER_REGISTRY,
    ) -> None:
        self._registry = registry
        self._evidence: dict[str, dict[str, ObservedProviderValue]] = {}

    def ingest(self, observation: ProviderRuntimeObservation) -> RuntimeProviderSnapshot:
        if observation.provider_id not in self._registry:
            raise KeyError(f"unknown provider_id: {observation.provider_id}")

        current = dict(self._evidence.get(observation.provider_id, {}))
        candidate = dict(current)

        for field_name, observed in observation.fields.items():
            existing = candidate.get(field_name)
            if existing is None:
                candidate[field_name] = observed
                continue

            new_at = observed.provenance.observed_at
            old_at = existing.provenance.observed_at
            if new_at > old_at:
                candidate[field_name] = observed
            elif new_at == old_at and observed.value != existing.value:
                raise EvidenceConflictError(
                    f"conflicting evidence for {observation.provider_id}.{field_name} "
                    f"at {new_at.isoformat()}"
                )

        snapshot = self._snapshot_from_fields(observation.provider_id, candidate)
        self._evidence[observation.provider_id] = candidate
        return snapshot

    def snapshot(self, provider_id: str) -> RuntimeProviderSnapshot:
        if provider_id not in self._registry:
            raise KeyError(f"unknown provider_id: {provider_id}")
        fields = self._evidence.get(provider_id)
        if not fields:
            raise KeyError(f"no runtime evidence for provider_id: {provider_id}")
        return self._snapshot_from_fields(provider_id, fields)

    def _snapshot_from_fields(
        self,
        provider_id: str,
        fields: Mapping[str, ObservedProviderValue],
    ) -> RuntimeProviderSnapshot:
        definition = self._registry[provider_id]
        values = {name: observed.value for name, observed in fields.items()}
        record = ProviderLifecycleRecord(
            provider_id=definition.provider_id,
            role=definition.role,
            market_scope=definition.market_scope,
            decision_criticality=definition.decision_criticality,
            fallback_provider=definition.fallback_provider,
            **values,
        )
        provenance = MappingProxyType({
            name: observed.provenance for name, observed in fields.items()
        })
        observed_at = max(
            observed.provenance.observed_at for observed in fields.values()
        )
        return RuntimeProviderSnapshot(
            record=record,
            field_provenance=provenance,
            observed_at=observed_at,
            evidence_count=len(fields),
        )
