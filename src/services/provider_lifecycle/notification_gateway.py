"""Thin bridge from provider alert transitions to the existing notification stack.

The gateway is intentionally delivery-only. It does not mutate Provider
Lifecycle state, re-evaluate alerts, select market-data fallbacks, change
billing, or authorize Radar/trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from .alert_engine import ProviderAlertTransition, ProviderAlertTransitionState
from .contract import GuardSeverity


class NotificationDispatcher(Protocol):
    def send_with_results(
        self,
        content: str,
        email_stock_codes: list[str] | None = None,
        email_send_to_all: bool = False,
        route_type: str | None = None,
        severity: str | None = None,
        dedup_key: str | None = None,
        cooldown_key: str | None = None,
        structured_payload: dict[str, Any] | None = None,
    ) -> object:
        ...


@dataclass(frozen=True)
class ProviderNotificationDispatch:
    transition: ProviderAlertTransition
    attempted: bool
    dispatched: bool
    success: bool
    status: str
    error_code: str | None = None
    retryable: bool = False


_SEVERITY = {
    GuardSeverity.INFO: "info",
    GuardSeverity.WARNING: "warning",
    GuardSeverity.CRITICAL: "critical",
}
_ALLOWED_DISPATCH_STATUSES = frozenset({
    "sent",
    "partial_failed",
    "all_failed",
    "no_channel",
    "noise_suppressed",
})
_RETRYABLE_DISPATCH_STATUSES = frozenset({
    "all_failed",
})


def _single_line(value: object) -> str:
    return " ".join(str(value).split())


def _notification_severity(transition: ProviderAlertTransition) -> str:
    if transition.state is ProviderAlertTransitionState.RESOLVED:
        return "info"
    return _SEVERITY[transition.severity]


def _dedup_key(transition: ProviderAlertTransition) -> str:
    return (
        f"{transition.alert_key}:{transition.state.value}:"
        f"{transition.evidence_at.isoformat()}"
    )


def _cooldown_key(transition: ProviderAlertTransition) -> str:
    # OPEN/UPDATED/RESOLVED use distinct cooldown buckets so a recovery message
    # cannot be suppressed by the earlier incident's cooldown window.
    return f"{transition.alert_key}:{transition.state.value}"


def _structured_payload(transition: ProviderAlertTransition) -> dict[str, Any]:
    return {
        "kind": "provider_lifecycle_alert",
        "provider_id": transition.provider_id,
        "code": transition.code,
        "transition_state": transition.state.value,
        "severity": _notification_severity(transition),
        "effective_health": transition.effective_health.value,
        "evidence_at": transition.evidence_at.isoformat(),
        "evaluated_at": transition.evaluated_at.isoformat(),
        "research_only": True,
        "data_admission": "NOT_EVALUATED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def _content(transition: ProviderAlertTransition) -> str:
    state = transition.state.value
    provider_id = _single_line(transition.provider_id)
    code = _single_line(transition.code)
    message = _single_line(transition.message)
    health = _single_line(transition.effective_health.value)
    return "\n".join([
        f"## Provider Lifecycle {state}",
        "",
        f"- Provider: {provider_id}",
        f"- Alert: {code}",
        f"- Health: {health}",
        f"- Detail: {message}",
        f"- Evidence: {transition.evidence_at.isoformat()}",
        "- Data Admission: NOT_EVALUATED",
        "- Radar Admission: BLOCKED",
        "- Live Trade: NO",
    ])


class ProviderNotificationGateway:
    """Dispatch provider alert transitions through an injected notification service."""

    def __init__(self, dispatcher: NotificationDispatcher) -> None:
        if dispatcher is None:
            raise ValueError("dispatcher is required")
        self._dispatcher = dispatcher

    def dispatch(
        self,
        transition: ProviderAlertTransition,
    ) -> ProviderNotificationDispatch:
        if not isinstance(transition, ProviderAlertTransition):
            raise TypeError("transition must be ProviderAlertTransition")

        severity = _notification_severity(transition)
        try:
            result = self._dispatcher.send_with_results(
                _content(transition),
                route_type="alert",
                severity=severity,
                dedup_key=_dedup_key(transition),
                cooldown_key=_cooldown_key(transition),
                structured_payload=_structured_payload(transition),
            )
        except Exception as exc:
            return ProviderNotificationDispatch(
                transition=transition,
                attempted=True,
                dispatched=False,
                success=False,
                status="dispatch_exception",
                error_code=f"dispatcher_exception:{type(exc).__name__}",
                retryable=True,
            )

        dispatched = getattr(result, "dispatched", None)
        success = getattr(result, "success", None)
        status = getattr(result, "status", None)
        if (
            not isinstance(dispatched, bool)
            or not isinstance(success, bool)
            or not isinstance(status, str)
            or status not in _ALLOWED_DISPATCH_STATUSES
        ):
            return ProviderNotificationDispatch(
                transition=transition,
                attempted=True,
                dispatched=False,
                success=False,
                status="invalid_dispatch_result",
                error_code="invalid_dispatch_result",
                retryable=True,
            )

        return ProviderNotificationDispatch(
            transition=transition,
            attempted=True,
            dispatched=dispatched,
            success=success,
            status=status,
            retryable=(not success and status in _RETRYABLE_DISPATCH_STATUSES),
        )

    def dispatch_many(
        self,
        transitions: Iterable[ProviderAlertTransition],
    ) -> tuple[ProviderNotificationDispatch, ...]:
        return tuple(self.dispatch(transition) for transition in transitions)
