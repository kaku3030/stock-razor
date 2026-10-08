"""In-memory runtime pipeline for Provider Lifecycle shadow validation.

The pipeline reuses the existing runtime-evidence builders, one shared
ProviderRuntimeObserver, and one shared ProviderShadowAlertValidator. It
performs no file I/O, network I/O, external notification, or trading action.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from .observer import (
    ProviderRuntimeObservation,
    ProviderRuntimeObserver,
    RuntimeProviderSnapshot,
)
from .runtime_ingest import (
    build_alpaca_observation_from_runtime_events,
    build_cn_provider_observations_from_cloud_snapshot,
    build_moomoo_opend_observation_from_livefeed_heartbeat,
    build_negative_provider_probe_observation,
)
from .shadow_validation import (
    ProviderShadowAlertResult,
    ProviderShadowAlertValidator,
)


@dataclass(frozen=True)
class ProviderShadowRuntimeCycle:
    source: str
    snapshots: tuple[RuntimeProviderSnapshot, ...]
    shadow_results: tuple[ProviderShadowAlertResult, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source is required")
        if len(self.snapshots) != len(self.shadow_results):
            raise ValueError(
                "snapshot count must match shadow result count"
            )
        if any(
            result.actual_notification_count != 0
            for result in self.shadow_results
        ):
            raise ValueError(
                "shadow runtime cycle must not contain external notifications"
            )

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(
            snapshot.record.provider_id
            for snapshot in self.snapshots
        )

    @property
    def transition_count(self) -> int:
        return sum(
            len(result.evaluation.transitions)
            for result in self.shadow_results
        )

    @property
    def planned_notification_count(self) -> int:
        return sum(
            len(result.notification_plans)
            for result in self.shadow_results
        )

    @property
    def actual_notification_count(self) -> int:
        return 0

    @property
    def validation_status(self) -> str:
        return "VALIDATED"

    @property
    def research_only(self) -> bool:
        return True

    @property
    def data_admission(self) -> str:
        return "NOT_EVALUATED"

    @property
    def radar_admission(self) -> str:
        return "BLOCKED"

    @property
    def live_trade(self) -> bool:
        return False


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _observation_time(observation: ProviderRuntimeObservation) -> datetime:
    return max(
        observed.provenance.observed_at
        for observed in observation.fields.values()
    )


class ProviderShadowRuntimePipeline:
    """Connect governed runtime evidence to the zero-delivery shadow harness."""

    def __init__(
        self,
        *,
        observer: ProviderRuntimeObserver | None = None,
        validator: ProviderShadowAlertValidator | None = None,
    ) -> None:
        self._observer = observer or ProviderRuntimeObserver()
        self._validator = validator or ProviderShadowAlertValidator()

    def _process(
        self,
        source: str,
        observations: Sequence[ProviderRuntimeObservation],
        *,
        now: datetime,
    ) -> ProviderShadowRuntimeCycle:
        _require_aware(now, "now")
        items = tuple(observations)
        if not items:
            raise ValueError("runtime pipeline observations must not be empty")

        # Preflight all timestamps before mutating the observer. Also protect
        # against evaluating an already-known provider state from the future.
        for observation in items:
            evidence_at = _observation_time(observation)
            if now < evidence_at:
                raise ValueError(
                    "now must not be before provider evidence observed_at"
                )
            try:
                existing = self._observer.snapshot(observation.provider_id)
            except KeyError:
                existing = None
            if existing is not None and now < existing.observed_at:
                raise ValueError(
                    "now must not be before existing provider observed_at"
                )

        snapshots = tuple(
            self._observer.ingest(observation)
            for observation in items
        )
        shadow_results = tuple(
            self._validator.evaluate(snapshot, now=now)
            for snapshot in snapshots
        )
        return ProviderShadowRuntimeCycle(
            source=source,
            snapshots=snapshots,
            shadow_results=shadow_results,
        )

    def process_opend_heartbeat(
        self,
        payload: Mapping[str, object],
        *,
        now: datetime,
    ) -> ProviderShadowRuntimeCycle:
        observation = build_moomoo_opend_observation_from_livefeed_heartbeat(
            payload
        )
        return self._process(
            "opend_heartbeat",
            (observation,),
            now=now,
        )

    def process_cn_cloud_observation(
        self,
        payload: Mapping[str, object],
        *,
        now: datetime,
    ) -> ProviderShadowRuntimeCycle:
        observations = build_cn_provider_observations_from_cloud_snapshot(
            payload
        )
        return self._process(
            "cn_cloud_observation",
            observations,
            now=now,
        )

    def process_alpaca_runtime_events(
        self,
        events: Sequence[Mapping[str, object]],
        *,
        repo_sha: str,
        now: datetime,
    ) -> ProviderShadowRuntimeCycle:
        observation = build_alpaca_observation_from_runtime_events(
            events,
            repo_sha=repo_sha,
        )
        return self._process(
            "alpaca_runtime_events",
            (observation,),
            now=now,
        )

    def process_negative_provider_probe(
        self,
        payload: Mapping[str, object],
        *,
        now: datetime,
    ) -> ProviderShadowRuntimeCycle:
        observation = build_negative_provider_probe_observation(payload)
        return self._process(
            "negative_provider_probe",
            (observation,),
            now=now,
        )
