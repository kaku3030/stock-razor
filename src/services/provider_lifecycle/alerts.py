"""Provider lifecycle alert transitions and notification bridge.

This layer turns Provider Guard assessments into meaningful notification
transitions. It does not change provider health, Data Admission, Radar
Admission, trading admission, spending, or execution permission.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from .contract import (
    GuardSeverity,
    ProviderAlert,
    ProviderGuardAssessment,
    ProviderHealthState,
)
from .observer import RuntimeProviderSnapshot


logger = logging.getLogger(__name__)

_ACTIVE_TRANSITIONS = frozenset({"ACTIVE", "CHANGED"})
_BENIGN_HEALTH = frozenset({
    ProviderHealthState.UNKNOWN,
    ProviderHealthState.HEALTHY,
})
_SEVERITY_RANK = {
    GuardSeverity.INFO: 0,
    GuardSeverity.WARNING: 1,
    GuardSeverity.CRITICAL: 2,
}


@dataclass(frozen=True)
class ProviderGuardNotification:
    provider_id: str
    transition: str
    severity: GuardSeverity
    effective_health: ProviderHealthState
    alert_codes: tuple[str, ...]
    messages: tuple[str, ...]
    observed_at: datetime
    decision_criticality: str
    user_approval_required: bool
    auto_spend_permitted: bool
    projected_exhaustion_at: datetime | None
    state_key: str
    radar_admission: str = "UNCHANGED"
    trading_admission: str = "UNCHANGED"
    live_trade: bool = False

    def __post_init__(self) -> None:
        if self.transition not in {"ACTIVE", "CHANGED", "CLEARED"}:
            raise ValueError(f"unsupported provider guard transition: {self.transition}")
        if not self.provider_id.strip():
            raise ValueError("provider_id is required")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.projected_exhaustion_at is not None and (
            self.projected_exhaustion_at.tzinfo is None
            or self.projected_exhaustion_at.utcoffset() is None
        ):
            raise ValueError("projected_exhaustion_at must be timezone-aware")
        if not self.state_key.strip():
            raise ValueError("state_key is required")
        if len(self.alert_codes) != len(self.messages):
            raise ValueError("alert_codes and messages must have the same length")
        if self.transition in _ACTIVE_TRANSITIONS and not self.alert_codes:
            raise ValueError("active provider guard notifications require alert codes")
        if self.transition == "CLEARED" and self.severity is not GuardSeverity.INFO:
            raise ValueError("cleared provider guard notifications must be INFO")
        if self.auto_spend_permitted:
            raise ValueError("provider guard notifications cannot permit automatic spend")
        if self.radar_admission != "UNCHANGED":
            raise ValueError("provider guard notifications cannot change Radar admission")
        if self.trading_admission != "UNCHANGED":
            raise ValueError("provider guard notifications cannot change trading admission")
        if self.live_trade:
            raise ValueError("provider guard notifications cannot enable live trading")


class ProviderGuardAlertEngine:
    """Emit one aggregated event only when provider guard state meaningfully changes."""

    def __init__(self) -> None:
        self._last_fingerprint: dict[str, tuple[str, tuple[str, ...], bool]] = {}
        self._last_active: dict[str, bool] = {}

    def evaluate(
        self,
        snapshot: RuntimeProviderSnapshot,
        assessment: ProviderGuardAssessment,
    ) -> tuple[ProviderGuardNotification, ...]:
        if snapshot.record.provider_id != assessment.provider_id:
            raise ValueError("provider guard assessment does not match runtime snapshot")
        if assessment.auto_spend_permitted:
            raise ValueError("Provider Guard assessment cannot permit automatic spend")

        alerts = list(assessment.alerts)
        implicit = _implicit_health_alert(assessment.effective_health)
        if implicit is not None:
            alerts.append(implicit)
        alerts.sort(key=lambda alert: (alert.code, alert.severity.value, alert.message))

        codes = tuple(alert.code for alert in alerts)
        messages = tuple(alert.message for alert in alerts)
        active = bool(alerts)
        fingerprint = (
            assessment.effective_health.value,
            codes,
            bool(assessment.user_approval_required),
        )

        provider_id = assessment.provider_id
        previous = self._last_fingerprint.get(provider_id)
        previous_active = self._last_active.get(provider_id, False)
        self._last_fingerprint[provider_id] = fingerprint
        self._last_active[provider_id] = active

        if previous == fingerprint:
            return ()

        if not active:
            if previous is None or not previous_active:
                return ()
            event = _build_cleared_notification(snapshot, assessment)
            return (event,)

        transition = "CHANGED" if previous_active else "ACTIVE"
        severity = max(
            (alert.severity for alert in alerts),
            key=lambda item: _SEVERITY_RANK[item],
        )
        state_key = _state_key(
            assessment.effective_health,
            codes,
            assessment.user_approval_required,
        )
        event = ProviderGuardNotification(
            provider_id=provider_id,
            transition=transition,
            severity=severity,
            effective_health=assessment.effective_health,
            alert_codes=codes,
            messages=messages,
            observed_at=snapshot.observed_at,
            decision_criticality=snapshot.record.decision_criticality,
            user_approval_required=assessment.user_approval_required,
            auto_spend_permitted=False,
            projected_exhaustion_at=assessment.projected_exhaustion_at,
            state_key=state_key,
        )
        return (event,)


class NotificationServiceProviderGuardSink:
    """Send provider guard transitions through the existing alert notification route."""

    def __init__(self, service: Any | None = None) -> None:
        if service is None:
            from src.notification import get_notification_service

            service = get_notification_service()
        self._service = service
        self.last_dispatch: Any | None = None
        self.last_error: str | None = None

    def __call__(self, event: ProviderGuardNotification) -> None:
        content = format_provider_guard_notification(event)
        dedup_key = (
            f"provider_guard:{event.provider_id}:{event.transition}:{event.state_key}"
        )
        cooldown_key = f"provider_guard:{event.provider_id}:{event.state_key}"
        try:
            self.last_dispatch = self._service.send_with_results(
                content,
                route_type="alert",
                severity=event.severity.value.lower(),
                dedup_key=dedup_key,
                cooldown_key=cooldown_key,
                structured_payload=provider_guard_structured_payload(event),
            )
            self.last_error = None
        except Exception as exc:
            self.last_error = type(exc).__name__
            logger.warning(
                "Provider Guard notification dispatch failed: %s",
                type(exc).__name__,
            )


def provider_guard_structured_payload(
    event: ProviderGuardNotification,
) -> dict[str, object]:
    return {
        "event_type": "provider_guard_alert",
        "provider_id": event.provider_id,
        "transition": event.transition,
        "severity": event.severity.value,
        "effective_health": event.effective_health.value,
        "alert_codes": list(event.alert_codes),
        "messages": list(event.messages),
        "observed_at": event.observed_at.isoformat(),
        "decision_criticality": event.decision_criticality,
        "user_approval_required": event.user_approval_required,
        "auto_spend_permitted": False,
        "projected_exhaustion_at": (
            event.projected_exhaustion_at.isoformat()
            if event.projected_exhaustion_at is not None
            else None
        ),
        "radar_admission": "UNCHANGED",
        "trading_admission": "UNCHANGED",
        "live_trade": False,
        "research_only": True,
    }


def format_provider_guard_notification(event: ProviderGuardNotification) -> str:
    title = {
        GuardSeverity.CRITICAL: "🚨 Provider Guard",
        GuardSeverity.WARNING: "⚠️ Provider Guard",
        GuardSeverity.INFO: "ℹ️ Provider Guard",
    }[event.severity]
    lines = [
        f"{title} — {event.provider_id}",
        "",
        f"- transition: {event.transition}",
        f"- effective health: {event.effective_health.value}",
        f"- decision criticality: {event.decision_criticality}",
    ]
    if event.alert_codes:
        lines.append(f"- alert codes: {', '.join(event.alert_codes)}")
    for message in event.messages:
        lines.append(f"- {message}")
    if event.projected_exhaustion_at is not None:
        lines.append(
            f"- projected exhaustion: {event.projected_exhaustion_at.isoformat()}"
        )
    lines.extend([
        f"- user approval required: {str(event.user_approval_required).lower()}",
        "- automatic spend: forbidden",
        "- Radar admission: unchanged",
        "- Trading admission: unchanged",
        "- LIVE_TRADE=NO",
        "",
        "> Provider lifecycle alert only. It is not a trade signal or execution instruction.",
    ])
    return "\n".join(lines)


def _implicit_health_alert(
    health: ProviderHealthState,
) -> ProviderAlert | None:
    if health in _BENIGN_HEALTH:
        return None
    severity = (
        GuardSeverity.CRITICAL
        if health in {
            ProviderHealthState.FAILED,
            ProviderHealthState.EXHAUSTED,
            ProviderHealthState.EXPIRED,
        }
        else GuardSeverity.WARNING
    )
    return ProviderAlert(
        severity=severity,
        code=f"PROVIDER_HEALTH_{health.value}",
        message=f"Provider effective health is {health.value.lower()}.",
    )


def _build_cleared_notification(
    snapshot: RuntimeProviderSnapshot,
    assessment: ProviderGuardAssessment,
) -> ProviderGuardNotification:
    code = "PROVIDER_GUARD_ALERTS_CLEARED"
    message = (
        "Previously active provider lifecycle conditions are no longer present. "
        f"Current effective health is {assessment.effective_health.value.lower()}; "
        "this does not imply Data, Radar, or Trading admission."
    )
    return ProviderGuardNotification(
        provider_id=assessment.provider_id,
        transition="CLEARED",
        severity=GuardSeverity.INFO,
        effective_health=assessment.effective_health,
        alert_codes=(code,),
        messages=(message,),
        observed_at=snapshot.observed_at,
        decision_criticality=snapshot.record.decision_criticality,
        user_approval_required=assessment.user_approval_required,
        auto_spend_permitted=False,
        projected_exhaustion_at=assessment.projected_exhaustion_at,
        state_key=_state_key(
            assessment.effective_health,
            (code,),
            assessment.user_approval_required,
        ),
    )


def _state_key(
    health: ProviderHealthState,
    codes: tuple[str, ...],
    user_approval_required: bool,
) -> str:
    code_part = "+".join(codes) if codes else "NONE"
    approval = "APPROVAL" if user_approval_required else "NO_APPROVAL"
    return f"{health.value}:{code_part}:{approval}"
