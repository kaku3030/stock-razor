"""Stateful Provider Lifecycle alert transition engine.

This module converts provider guard assessments into typed OPEN / UPDATED /
RESOLVED transitions. It does not poll providers, send notifications, make
Data Admission decisions, change spend settings, or authorize execution.
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
    alert_key: str
    research_only: bool = True
    data_admission: str = "NOT_EVALUATED"
    radar_admission: str = "BLOCKED"
    live_trade: bool = False


@dataclass(frozen=True)
class ProviderAlertEvaluation:
    assessment: ProviderGuardAssessment
    transitions: tuple[ProviderAlertTransition, ...]
    active_alerts: tuple[ProviderAlert, ...]


class StaleProviderAlertEvidenceError(ValueError):
    """Raised when older provider evidence attempts to roll alert state back."""


_RUNTIME_SEVERITY: Mapping[ProviderHealthState, GuardSeverity] = {
    ProviderHealthState.WARNING: GuardSeverity.WARNING,
    ProviderHealthState.DEGRADED: GuardSeverity.WARNING,
    ProviderHealthState.RATE_LIMITED: GuardSeverity.WARNING,
    ProviderHealthState.FAILED: GuardSeverity.CRITICAL,
    ProviderHealthState.EXHAUSTED: GuardSeverity.CRITICAL,
    ProviderHealthState.EXPIRED: GuardSeverity.CRITICAL,
}

_RUNTIME_STATE_REPRESENTED_BY_CODES: Mapping[
    ProviderHealthState,
    frozenset[str],
] = {
    ProviderHealthState.EXPIRED: frozenset({
        "CREDENTIAL_EXPIRED",
        "CREDENTIAL_STATUS_EXPIRED",
    }),
    ProviderHealthState.EXHAUSTED: frozenset({
        "BILLING_STATUS_EXHAUSTED",
        "QUOTA_EXHAUSTED",
    }),
    ProviderHealthState.FAILED: frozenset({
        "BILLING_STATUS_FAILED",
        "CREDENTIAL_STATUS_FAILED",
    }),
}


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _runtime_health_alert(
    state: ProviderHealthState,
    *,
    assessment_alerts: tuple[ProviderAlert, ...],
) -> ProviderAlert | None:
    severity = _RUNTIME_SEVERITY.get(state)
    if severity is None:
        return None

    assessment_codes = {alert.code for alert in assessment_alerts}
    represented = _RUNTIME_STATE_REPRESENTED_BY_CODES.get(state, frozenset())
    if assessment_codes.intersection(represented):
        return None

    # A generic WARNING adds little value when a more specific guard warning
    # already exists. DEGRADED/RATE_LIMITED remain explicit because the guard
    # assessment currently has no dedicated transport/rate-state alert.
    if state is ProviderHealthState.WARNING and assessment_alerts:
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

    runtime_alert = _runtime_health_alert(
        snapshot.record.health_state,
        assessment_alerts=assessment.alerts,
    )
    if runtime_alert is not None:
        existing = desired.get(runtime_alert.code)
        if existing is not None and existing != runtime_alert:
            raise ValueError(
                f"conflicting provider alert code: {runtime_alert.code}"
            )
        desired[runtime_alert.code] = runtime_alert

    return desired


def _transition(
    *,
    provider_id: str,
    alert: ProviderAlert,
    state: ProviderAlertTransitionState,
    evidence_at: datetime,
    evaluated_at: datetime,
    effective_health: ProviderHealthState,
) -> ProviderAlertTransition:
    return ProviderAlertTransition(
        provider_id=provider_id,
        code=alert.code,
        state=state,
        severity=alert.severity,
        message=alert.message,
        evidence_at=evidence_at,
        evaluated_at=evaluated_at,
        effective_health=effective_health,
        alert_key=f"provider_lifecycle:{provider_id}:{alert.code}",
    )


class ProviderAlertEngine:
    """Convert provider snapshots into deduplicated alert state transitions."""

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
        if now < snapshot.observed_at:
            raise ValueError("now must not be before snapshot.observed_at")

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
            transitions.append(_transition(
                provider_id=provider_id,
                alert=previous[code],
                state=ProviderAlertTransitionState.RESOLVED,
                evidence_at=snapshot.observed_at,
                evaluated_at=now,
                effective_health=assessment.effective_health,
            ))

        for code in sorted(desired):
            current = desired[code]
            old = previous.get(code)
            if old is None:
                state = ProviderAlertTransitionState.OPEN
            elif old == current:
                continue
            else:
                state = ProviderAlertTransitionState.UPDATED
            transitions.append(_transition(
                provider_id=provider_id,
                alert=current,
                state=state,
                evidence_at=snapshot.observed_at,
                evaluated_at=now,
                effective_health=assessment.effective_health,
            ))

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
        if provider_id != provider_id.strip():
            raise ValueError("provider_id must not contain outer whitespace")
        active = self._active.get(provider_id, {})
        return tuple(active[code] for code in sorted(active))
