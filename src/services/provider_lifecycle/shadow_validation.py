"""Shadow validation harness for Provider Lifecycle alerts.

This module executes the real Provider Alert Engine and Provider Notification
Gateway against an in-memory notification sink. It never calls configured
notification channels and never touches trading execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from .alert_engine import (
    ProviderAlertEngine,
    ProviderAlertEvaluation,
)
from .notification_gateway import (
    ProviderNotificationDispatch,
    ProviderNotificationGateway,
)
from .observer import RuntimeProviderSnapshot


@dataclass(frozen=True)
class ProviderShadowNotificationPlan:
    content: str
    route_type: str
    severity: str
    dedup_key: str
    cooldown_key: str
    structured_payload: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "structured_payload",
            MappingProxyType(dict(self.structured_payload)),
        )


@dataclass(frozen=True)
class ProviderShadowAlertResult:
    evaluation: ProviderAlertEvaluation
    notification_plans: tuple[ProviderShadowNotificationPlan, ...]
    dispatches: tuple[ProviderNotificationDispatch, ...]
    validation_status: str = "VALIDATED"
    actual_notification_count: int = 0
    research_only: bool = True
    data_admission: str = "NOT_EVALUATED"
    radar_admission: str = "BLOCKED"
    live_trade: bool = False


@dataclass(frozen=True)
class _ShadowDispatchResult:
    dispatched: bool = False
    success: bool = False
    status: str = "shadow_only"
    channel_results: tuple[object, ...] = ()


class _ShadowNotificationService:
    """In-memory NotificationService-compatible sink with zero I/O."""

    def __init__(self) -> None:
        self.plans: list[ProviderShadowNotificationPlan] = []

    def send_with_results(
        self,
        content: str,
        *,
        route_type: str | None = None,
        severity: str | None = None,
        dedup_key: str | None = None,
        cooldown_key: str | None = None,
        structured_payload: Mapping[str, object] | None = None,
    ) -> _ShadowDispatchResult:
        if route_type != "alert":
            raise ValueError("shadow provider notification route must be alert")
        if severity not in {"info", "warning", "critical"}:
            raise ValueError("shadow provider notification severity is invalid")
        if not isinstance(dedup_key, str) or not dedup_key:
            raise ValueError("shadow provider notification dedup_key is required")
        if not isinstance(cooldown_key, str) or not cooldown_key:
            raise ValueError("shadow provider notification cooldown_key is required")
        if not isinstance(structured_payload, Mapping):
            raise ValueError(
                "shadow provider notification structured_payload is required"
            )
        if structured_payload.get("research_only") is not True:
            raise ValueError("shadow provider notification must be research_only")
        if structured_payload.get("data_admission") != "NOT_EVALUATED":
            raise ValueError(
                "shadow provider notification must not carry Data Admission"
            )
        if structured_payload.get("radar_admission") != "BLOCKED":
            raise ValueError(
                "shadow provider notification must preserve RADAR_ADMISSION=BLOCKED"
            )
        if structured_payload.get("live_trade") is not False:
            raise ValueError(
                "shadow provider notification must preserve LIVE_TRADE=NO"
            )

        self.plans.append(ProviderShadowNotificationPlan(
            content=content,
            route_type=route_type,
            severity=severity,
            dedup_key=dedup_key,
            cooldown_key=cooldown_key,
            structured_payload=structured_payload,
        ))
        return _ShadowDispatchResult()


class ProviderShadowAlertValidator:
    """Run provider alert + notification contracts without external delivery."""

    def __init__(
        self,
        engine: ProviderAlertEngine | None = None,
    ) -> None:
        self._engine = engine or ProviderAlertEngine()

    def evaluate(
        self,
        snapshot: RuntimeProviderSnapshot,
        *,
        now: datetime,
    ) -> ProviderShadowAlertResult:
        evaluation = self._engine.evaluate(snapshot, now=now)
        sink = _ShadowNotificationService()
        gateway = ProviderNotificationGateway(sink)

        dispatches = tuple(
            gateway.dispatch(transition)
            for transition in evaluation.transitions
        )
        plans = tuple(sink.plans)

        if len(plans) != len(evaluation.transitions):
            raise RuntimeError(
                "shadow notification plan count does not match alert transitions"
            )
        if len(dispatches) != len(plans):
            raise RuntimeError(
                "shadow dispatch count does not match notification plans"
            )
        if any(
            dispatch.attempted
            or dispatch.success
            or dispatch.status != "shadow_only"
            for dispatch in dispatches
        ):
            raise RuntimeError(
                "shadow provider validation attempted external notification"
            )

        return ProviderShadowAlertResult(
            evaluation=evaluation,
            notification_plans=plans,
            dispatches=dispatches,
        )
