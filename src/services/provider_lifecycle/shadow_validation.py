"""Research-only shadow validation for Provider Lifecycle alert transitions.

This module runs the Provider Alert Engine against real/provider-runtime
snapshots and records deterministic would-be alert transitions without invoking
notification delivery. It cannot activate notifications or change any
admission/execution state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Iterable

from .alert_engine import (
    ProviderAlertEngine,
    ProviderAlertEvaluation,
    ProviderAlertTransition,
)
from .contract import GuardSeverity, ProviderHealthState
from .observer import RuntimeProviderSnapshot


@dataclass(frozen=True)
class ProviderAlertShadowEvent:
    shadow_event_id: str
    provider_id: str
    code: str
    transition_state: str
    severity: GuardSeverity
    message: str
    evidence_at: datetime
    evaluated_at: datetime
    effective_health: ProviderHealthState
    alert_key: str
    route_type: str = "alert"
    shadow_only: bool = True
    delivery_attempted: bool = False
    research_only: bool = True
    data_admission: str = "NOT_EVALUATED"
    radar_admission: str = "BLOCKED"
    live_trade: bool = False


@dataclass(frozen=True)
class ProviderAlertShadowBatch:
    evaluation: ProviderAlertEvaluation
    events: tuple[ProviderAlertShadowEvent, ...]


@dataclass(frozen=True)
class ProviderAlertShadowSummary:
    snapshot_count: int
    transition_count: int
    open_count: int
    updated_count: int
    resolved_count: int
    completed_cycle_count: int
    active_alert_count: int
    providers_observed: tuple[str, ...]
    codes_seen: tuple[str, ...]
    shadow_status: str
    notification_activation_permitted: bool = False
    research_only: bool = True
    data_admission: str = "NOT_EVALUATED"
    radar_admission: str = "BLOCKED"
    live_trade: bool = False


def _shadow_event_id(transition: ProviderAlertTransition) -> str:
    material = "|".join(
        (
            transition.provider_id,
            transition.code,
            transition.state.value,
            transition.severity.value,
            transition.effective_health.value,
            transition.evidence_at.isoformat(),
            transition.evaluated_at.isoformat(),
            transition.alert_key,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"provider-alert-shadow-{digest[:32]}"


def _shadow_event(
    transition: ProviderAlertTransition,
) -> ProviderAlertShadowEvent:
    return ProviderAlertShadowEvent(
        shadow_event_id=_shadow_event_id(transition),
        provider_id=transition.provider_id,
        code=transition.code,
        transition_state=transition.state.value,
        severity=transition.severity,
        message=transition.message,
        evidence_at=transition.evidence_at,
        evaluated_at=transition.evaluated_at,
        effective_health=transition.effective_health,
        alert_key=transition.alert_key,
    )


class ProviderAlertShadowValidator:
    """Run provider alerts in shadow mode and retain an immutable audit journal."""

    def __init__(self, engine: ProviderAlertEngine | None = None) -> None:
        self._engine = engine or ProviderAlertEngine()
        self._events: list[ProviderAlertShadowEvent] = []
        self._event_ids: set[str] = set()
        self._snapshot_count = 0
        self._providers_observed: set[str] = set()
        self._codes_seen: set[str] = set()

    def observe(
        self,
        snapshot: RuntimeProviderSnapshot,
        *,
        now: datetime,
    ) -> ProviderAlertShadowBatch:
        if not isinstance(snapshot, RuntimeProviderSnapshot):
            raise TypeError("snapshot must be RuntimeProviderSnapshot")

        # ProviderAlertEngine performs the authoritative causal/staleness checks.
        # We mutate shadow counters only after a successful evaluation.
        evaluation = self._engine.evaluate(snapshot, now=now)
        self._snapshot_count += 1
        self._providers_observed.add(snapshot.record.provider_id)

        new_events: list[ProviderAlertShadowEvent] = []
        for transition in evaluation.transitions:
            event = _shadow_event(transition)
            if event.shadow_event_id in self._event_ids:
                # The engine is stateful and normally prevents duplicates. This
                # extra guard keeps the shadow journal idempotent if an identical
                # transition is ever replayed through a restored engine.
                continue
            self._event_ids.add(event.shadow_event_id)
            self._events.append(event)
            self._codes_seen.add(event.code)
            new_events.append(event)

        return ProviderAlertShadowBatch(
            evaluation=evaluation,
            events=tuple(new_events),
        )

    def observe_many(
        self,
        items: Iterable[tuple[RuntimeProviderSnapshot, datetime]],
    ) -> tuple[ProviderAlertShadowBatch, ...]:
        return tuple(
            self.observe(snapshot, now=now)
            for snapshot, now in items
        )

    def journal(self) -> tuple[ProviderAlertShadowEvent, ...]:
        return tuple(self._events)

    def summary(self) -> ProviderAlertShadowSummary:
        open_count = sum(event.transition_state == "OPEN" for event in self._events)
        updated_count = sum(event.transition_state == "UPDATED" for event in self._events)
        resolved_count = sum(
            event.transition_state == "RESOLVED"
            for event in self._events
        )
        active_alert_count = sum(
            len(self._engine.active_alerts(provider_id))
            for provider_id in self._providers_observed
        )
        return ProviderAlertShadowSummary(
            snapshot_count=self._snapshot_count,
            transition_count=len(self._events),
            open_count=open_count,
            updated_count=updated_count,
            resolved_count=resolved_count,
            completed_cycle_count=resolved_count,
            active_alert_count=active_alert_count,
            providers_observed=tuple(sorted(self._providers_observed)),
            codes_seen=tuple(sorted(self._codes_seen)),
            shadow_status=(
                "EVIDENCE_AVAILABLE"
                if self._events
                else "COLLECTING"
            ),
        )
