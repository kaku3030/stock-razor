"""Notification gateway for Provider Lifecycle alert transitions.

This bridge reuses the repository's existing NotificationService alert route.
Notification delivery is strictly downstream of lifecycle/alert state: a send
failure must never mutate Provider Health, Data Admission, Radar Admission, or
execution authorization.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.notification_routing import ROUTABLE_NOTIFICATION_CHANNEL_SET

from .alert_engine import (
    ProviderAlertTransition,
    ProviderAlertTransitionState,
)
from .contract import GuardSeverity, ProviderHealthState


class ProviderNotificationPolicyError(ValueError):
    """Raised when a transition violates frozen notification governance."""


@dataclass(frozen=True)
class ProviderNotificationChannelResult:
    channel: str
    success: bool
    error_code: str | None = None
    retryable: bool = False
    latency_ms: int | None = None


@dataclass(frozen=True)
class ProviderNotificationDispatch:
    transition: ProviderAlertTransition
    attempted: bool
    success: bool
    status: str
    dedup_key: str
    cooldown_key: str
    channel_results: tuple[ProviderNotificationChannelResult, ...] = ()
    error_type: str | None = None


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderNotificationPolicyError(
            f"{field_name} must be timezone-aware"
        )


_PROVIDER_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789._-"
)
_ALERT_CODE_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


def _validate_identity_token(
    value: object,
    field_name: str,
    *,
    allowed: frozenset[str],
    max_length: int,
) -> str:
    if not isinstance(value, str):
        raise ProviderNotificationPolicyError(f"{field_name} must be a string")
    if (
        not value
        or value != value.strip()
        or len(value) > max_length
        or any(ch not in allowed for ch in value)
    ):
        raise ProviderNotificationPolicyError(
            f"{field_name} contains unsupported identity characters"
        )
    return value


def _validate_transition(transition: ProviderAlertTransition) -> None:
    if not isinstance(transition, ProviderAlertTransition):
        raise TypeError("transition must be ProviderAlertTransition")
    if not isinstance(transition.state, ProviderAlertTransitionState):
        raise ProviderNotificationPolicyError(
            "transition.state must be ProviderAlertTransitionState"
        )
    if not isinstance(transition.severity, GuardSeverity):
        raise ProviderNotificationPolicyError(
            "transition.severity must be GuardSeverity"
        )
    if not isinstance(transition.effective_health, ProviderHealthState):
        raise ProviderNotificationPolicyError(
            "transition.effective_health must be ProviderHealthState"
        )

    provider_id = _validate_identity_token(
        transition.provider_id,
        "provider_id",
        allowed=_PROVIDER_ID_CHARS,
        max_length=80,
    )
    code = _validate_identity_token(
        transition.code,
        "code",
        allowed=_ALERT_CODE_CHARS,
        max_length=120,
    )

    _require_aware(transition.evidence_at, "evidence_at")
    _require_aware(transition.evaluated_at, "evaluated_at")
    if transition.evaluated_at < transition.evidence_at:
        raise ProviderNotificationPolicyError(
            "evaluated_at must not be before evidence_at"
        )
    if transition.research_only is not True:
        raise ProviderNotificationPolicyError(
            "provider notifications must remain research_only"
        )
    if transition.data_admission != "NOT_EVALUATED":
        raise ProviderNotificationPolicyError(
            "provider notification cannot carry Data Admission"
        )
    if transition.radar_admission != "BLOCKED":
        raise ProviderNotificationPolicyError(
            "provider notification must preserve RADAR_ADMISSION=BLOCKED"
        )
    if transition.live_trade is not False:
        raise ProviderNotificationPolicyError(
            "provider notification must preserve LIVE_TRADE=NO"
        )

    if (
        not transition.message
        or len(transition.message) > 240
        or "\n" in transition.message
        or "\r" in transition.message
    ):
        raise ProviderNotificationPolicyError(
            "provider alert message must be a single line up to 240 characters"
        )

    expected_key = f"provider_lifecycle:{provider_id}:{code}"
    if transition.alert_key != expected_key:
        raise ProviderNotificationPolicyError(
            "provider alert_key does not match provider/code identity"
        )


def _message_digest(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]


def _evidence_digest(transition: ProviderAlertTransition) -> str:
    normalized = transition.evidence_at.astimezone(timezone.utc).isoformat(
        timespec="microseconds"
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _dedup_key(transition: ProviderAlertTransition) -> str:
    return (
        f"{transition.alert_key}:{transition.state.value}:"
        f"{transition.severity.value}:{_evidence_digest(transition)}:"
        f"{_message_digest(transition.message)}"
    )


def _cooldown_key(transition: ProviderAlertTransition) -> str:
    # State- and evidence-specific cooldown means a recovery or a later
    # re-open cannot be suppressed by an earlier incident's cooldown window.
    return (
        f"{transition.alert_key}:{transition.state.value}:"
        f"{_evidence_digest(transition)}"
    )


def _severity(transition: ProviderAlertTransition) -> str:
    # Preserve the originating alert severity for RESOLVED events so recovery
    # from a critical incident is not silently filtered by min-severity policy.
    return transition.severity.value.lower()


def _safe_bool(value: object) -> bool:
    return value if isinstance(value, bool) else False


def format_provider_notification(transition: ProviderAlertTransition) -> str:
    """Render a deterministic, secret-free Provider Lifecycle notification."""

    _validate_transition(transition)
    resolved = transition.state is ProviderAlertTransitionState.RESOLVED
    title = (
        "✅ **Provider Lifecycle：恢复通知**"
        if resolved
        else "⚠️ **Provider Lifecycle：状态告警**"
    )
    return "\n".join([
        title,
        "",
        f"- provider: {transition.provider_id}",
        f"- transition: {transition.state.value}",
        f"- code: {transition.code}",
        f"- severity: {_severity(transition)}",
        f"- effective health: {transition.effective_health.value}",
        f"- evidence at: {transition.evidence_at.isoformat()}",
        f"- evaluated at: {transition.evaluated_at.isoformat()}",
        f"- message: {transition.message}",
        "",
        "> Research-only Provider Guard notification. "
        "Data Admission is not evaluated; Radar admission remains BLOCKED; "
        "LIVE_TRADE remains NO.",
    ])


def _structured_payload(
    transition: ProviderAlertTransition,
) -> dict[str, object]:
    return {
        "event_type": "provider_lifecycle_alert",
        "provider_id": transition.provider_id,
        "transition_state": transition.state.value,
        "code": transition.code,
        "severity": _severity(transition),
        "effective_health": transition.effective_health.value,
        "evidence_at": transition.evidence_at.isoformat(),
        "evaluated_at": transition.evaluated_at.isoformat(),
        "research_only": True,
        "data_admission": "NOT_EVALUATED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


_RESULT_TOKEN_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "._-:/"
)
_ALLOWED_DISPATCH_STATUSES = frozenset({
    "sent",
    "all_failed",
    "no_channel",
    "partial_failed",
    "noise_suppressed",
})
_ALLOWED_CHANNELS = frozenset({
    "__context__",
    *ROUTABLE_NOTIFICATION_CHANNEL_SET,
})
_ALLOWED_ERROR_CODES = frozenset({
    "send_failed",
    "exception",
})


def _safe_result_token(
    value: object,
    *,
    fallback: str | None = None,
    max_length: int = 80,
) -> str | None:
    if value is None:
        return fallback
    token = str(value).strip()
    if (
        not token
        or len(token) > max_length
        or any(ch not in _RESULT_TOKEN_CHARS for ch in token)
    ):
        return fallback
    return token


def _dispatch_status(result: object) -> str:
    status = _safe_result_token(
        getattr(result, "status", None),
        fallback="unknown",
    )
    return status if status in _ALLOWED_DISPATCH_STATUSES else "unknown"


def _channel_results(result: object) -> tuple[ProviderNotificationChannelResult, ...]:
    items = getattr(result, "channel_results", ()) or ()
    if not isinstance(items, (list, tuple)):
        return ()

    output: list[ProviderNotificationChannelResult] = []
    for item in items:
        channel = _safe_result_token(
            getattr(item, "channel", None),
            fallback="unknown",
        )
        if channel not in _ALLOWED_CHANNELS:
            channel = "unknown"
        error_code = _safe_result_token(
            getattr(item, "error_code", None),
        )
        if error_code not in _ALLOWED_ERROR_CODES:
            error_code = None
        latency = getattr(item, "latency_ms", None)
        if not isinstance(latency, int) or isinstance(latency, bool) or latency < 0:
            latency = None
        output.append(ProviderNotificationChannelResult(
            channel=channel[:80],
            success=_safe_bool(getattr(item, "success", False)),
            error_code=error_code,
            retryable=_safe_bool(getattr(item, "retryable", False)),
            latency_ms=latency,
        ))
    return tuple(output)


class ProviderNotificationGateway:
    """Dispatch Provider Alert Engine transitions through NotificationService."""

    def __init__(self, service: Any | None = None) -> None:
        self._service = service

    def _notification_service(self) -> Any:
        if self._service is None:
            from src.notification import get_notification_service

            self._service = get_notification_service()
        return self._service

    def dispatch(
        self,
        transition: ProviderAlertTransition,
    ) -> ProviderNotificationDispatch:
        _validate_transition(transition)
        content = format_provider_notification(transition)
        dedup_key = _dedup_key(transition)
        cooldown_key = _cooldown_key(transition)

        try:
            result = self._notification_service().send_with_results(
                content,
                route_type="alert",
                severity=_severity(transition),
                dedup_key=dedup_key,
                cooldown_key=cooldown_key,
                structured_payload=_structured_payload(transition),
            )
        except Exception as exc:
            # Never persist raw exception text from external notification
            # providers. Delivery failure is diagnostic-only and cannot mutate
            # lifecycle or alert-engine state.
            return ProviderNotificationDispatch(
                transition=transition,
                attempted=True,
                success=False,
                status="exception",
                dedup_key=dedup_key,
                cooldown_key=cooldown_key,
                error_type=type(exc).__name__,
            )

        return ProviderNotificationDispatch(
            transition=transition,
            attempted=_safe_bool(getattr(result, "dispatched", False)),
            success=_safe_bool(getattr(result, "success", False)),
            status=_dispatch_status(result),
            dedup_key=dedup_key,
            cooldown_key=cooldown_key,
            channel_results=_channel_results(result),
        )
