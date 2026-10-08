"""Stateful provider lifecycle alert transitions.

This module consumes the existing provider guard assessment. It does not poll
providers, send notifications, change spend settings, make Data Admission
decisions, or authorize execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping

from .contract import (
    GuardSeverity,
    ProviderAlert,
    ProviderGuardAssessment,
    ProviderHealthState,
    assess_provider,
)
from .observer import RuntimeProviderSnapshot


class ProviderAlertTransitionState(str, Enum):
    OPEN = "OPEN"
    UPDATED = "UPDATED"
    RESOLVED = "RESOLVED"


@dataclass(frozen=True)
class ProviderAlertTransition:
    provider_id: str
    code: str
    state: ProviderAlertTransitionState
    severity: GuardSeverity
    message: str
    evidence_at: datetime
    evaluated_at: datetime
    effective_health: ProviderHealthState


@dataclass(frozen=True)
class ProviderAlertEvaluation:
    assessment: ProviderGuardAssessment
    transitions: tuple[ProviderAlertTransition, ...]
    active_alerts: tuple[ProviderAlert, ...]


class StaleProviderAlertEvidenceError(ValueError):
    """Raised when an older provider snapshot attempts to roll alert state back."""


_RUNTIME_SEVERITY: Mapping[ProviderHealthState, GuardSeverity] = {
    ProviderHealthState.WARNING: GuardSeverity.WARNING,
    ProviderHealthState.DEGRADED: GuardSeverity.WARNING,
    ProviderHealthState.RATE_LIMITED: GuardSeverity.WARNING,
    ProviderHealthState.FAILED: GuardSeverity.CRITICAL,
    ProviderHealthState.EXHAUSTED: GuardSeverity.CRITICAL,
    ProviderHealthState.EXPIRED: GuardSeverity.CRITICAL,
}


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _runtime_health_alert(state: ProviderHealthState) -> ProviderAlert | None:
    severity = _RUNTIME_SEVERITY.get(state)
    if severity is None:
        return None
    return ProviderAlert(
        severity=severity,
        code=f"RUNTIME_HEALTH_{state.value}",
        message=f"Provider runtime health is {state.value.lower()}.",
    )


def _desired_alerts(
    snapshot: RuntimeProviderSnapshot,
    assessment: ProviderGuardAssessment,
) -> dict[str, ProviderAlert]:
    desired: dict[str, ProviderAlert] = {}

    for alert in assessment.alerts:
        existing = desired.get(alert.code)
        if existing is not None and existing != alert:
            raise ValueError(f"conflicting provider alert code: {alert.code}")
        desired[alert.code] = alert

    runtime_alert = _runtime_health_alert(snapshot.record.health_state)
    if runtime_alert is not None:
        existing = desired.get(runtime_alert.code)
        if existing is not None and existing != runtime_alert:
            raise ValueError(
                f"conflicting provider alert code: {runtime_alert.code}"
            )
        desired[runtime_alert.code] = runtime_alert

    return desired


class ProviderAlertEngine:
    """Convert guard assessments into deduplicated alert state transitions."""

    def __init__(self) -> None:
        self._active: dict[str, dict[str, ProviderAlert]] = {}
        self._last_evidence_at: dict[str, datetime] = {}

    def evaluate(
        self,
        snapshot: RuntimeProviderSnapshot,
        *,
        now: datetime,
    ) -> ProviderAlertEvaluation:
        if not isinstance(snapshot, RuntimeProviderSnapshot):
            raise TypeError("snapshot must be RuntimeProviderSnapshot")
        _require_aware(now, "now")
        _require_aware(snapshot.observed_at, "snapshot.observed_at")

        provider_id = snapshot.record.provider_id
        previous_evidence_at = self._last_evidence_at.get(provider_id)
        if (
            previous_evidence_at is not None
            and snapshot.observed_at < previous_evidence_at
        ):
            raise StaleProviderAlertEvidenceError(
                f"older provider alert evidence rejected for {provider_id}: "
                f"{snapshot.observed_at.isoformat()} < "
                f"{previous_evidence_at.isoformat()}"
            )

        assessment = assess_provider(snapshot.record, now=now)
        desired = _desired_alerts(snapshot, assessment)
        previous = dict(self._active.get(provider_id, {}))

        transitions: list[ProviderAlertTransition] = []

        for code in sorted(previous):
            if code in desired:
                continue
            old = previous[code]
            transitions.append(
                ProviderAlertTransition(
                    provider_id=provider_id,
                    code=code,
                    state=ProviderAlertTransitionState.RESOLVED,
                    severity=old.severity,
                    message=old.message,
                    evidence_at=snapshot.observed_at,
                    evaluated_at=now,
                    effective_health=assessment.effective_health,
                )
            )

        for code in sorted(desired):
            current = desired[code]
            old = previous.get(code)
            if old is None:
                state = ProviderAlertTransitionState.OPEN
            elif old == current:
                continue
            else:
                state = ProviderAlertTransitionState.UPDATED
            transitions.append(
                ProviderAlertTransition(
                    provider_id=provider_id,
                    code=code,
                    state=state,
                    severity=current.severity,
                    message=current.message,
                    evidence_at=snapshot.observed_at,
                    evaluated_at=now,
                    effective_health=assessment.effective_health,
                )
            )

        self._active[provider_id] = desired
        if (
            previous_evidence_at is None
            or snapshot.observed_at > previous_evidence_at
        ):
            self._last_evidence_at[provider_id] = snapshot.observed_at

        active_alerts = tuple(desired[code] for code in sorted(desired))
        return ProviderAlertEvaluation(
            assessment=assessment,
            transitions=tuple(transitions),
            active_alerts=active_alerts,
        )

    def active_alerts(self, provider_id: str) -> tuple[ProviderAlert, ...]:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider_id is required")
        active = self._active.get(provider_id, {})
        return tuple(active[code] for code in sorted(active))
