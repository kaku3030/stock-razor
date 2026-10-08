from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from src.services.provider_lifecycle import (
    GuardSeverity,
    ProviderAlertTransition,
    ProviderAlertTransitionState,
    ProviderHealthState,
    ProviderNotificationGateway,
)


NOW = datetime(2026, 10, 8, 3, 45, tzinfo=timezone.utc)


@dataclass
class FakeDispatchResult:
    dispatched: bool
    success: bool
    status: str


class FakeDispatcher:
    def __init__(self, result=None, *, error=None):
        self.result = result or FakeDispatchResult(True, True, "sent")
        self.error = error
        self.calls = []

    def send_with_results(self, content, **kwargs):
        self.calls.append((content, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


class InvalidDispatcher:
    def send_with_results(self, content, **kwargs):
        return object()


def transition(
    *,
    state=ProviderAlertTransitionState.OPEN,
    severity=GuardSeverity.CRITICAL,
    message="Provider runtime health is failed.",
):
    return ProviderAlertTransition(
        provider_id="openai",
        code="RUNTIME_HEALTH_FAILED",
        state=state,
        severity=severity,
        message=message,
        evidence_at=NOW,
        evaluated_at=NOW,
        effective_health=ProviderHealthState.FAILED,
        alert_key="provider_lifecycle:openai:RUNTIME_HEALTH_FAILED",
    )


def test_open_transition_uses_existing_alert_route_and_critical_severity():
    dispatcher = FakeDispatcher()
    result = ProviderNotificationGateway(dispatcher).dispatch(transition())

    assert result.success is True
    assert result.status == "sent"
    assert len(dispatcher.calls) == 1
    content, kwargs = dispatcher.calls[0]
    assert kwargs["route_type"] == "alert"
    assert kwargs["severity"] == "critical"
    assert kwargs["dedup_key"] == (
        "provider_lifecycle:openai:RUNTIME_HEALTH_FAILED:"
        "OPEN:2026-10-08T03:45:00+00:00"
    )
    assert kwargs["cooldown_key"] == (
        "provider_lifecycle:openai:RUNTIME_HEALTH_FAILED:OPEN"
    )
    assert "Radar Admission: BLOCKED" in content
    assert "Live Trade: NO" in content


def test_resolved_transition_is_info_and_has_separate_cooldown_bucket():
    dispatcher = FakeDispatcher()
    gateway = ProviderNotificationGateway(dispatcher)
    gateway.dispatch(transition())
    gateway.dispatch(
        transition(state=ProviderAlertTransitionState.RESOLVED)
    )

    _, open_kwargs = dispatcher.calls[0]
    _, resolved_kwargs = dispatcher.calls[1]
    assert resolved_kwargs["severity"] == "info"
    assert open_kwargs["cooldown_key"].endswith(":OPEN")
    assert resolved_kwargs["cooldown_key"].endswith(":RESOLVED")
    assert open_kwargs["cooldown_key"] != resolved_kwargs["cooldown_key"]


def test_warning_maps_to_warning():
    dispatcher = FakeDispatcher()
    ProviderNotificationGateway(dispatcher).dispatch(
        transition(
            severity=GuardSeverity.WARNING,
            message="Provider runtime health is degraded.",
        )
    )
    assert dispatcher.calls[0][1]["severity"] == "warning"


def test_structured_payload_contains_only_delivery_safe_governance_fields():
    dispatcher = FakeDispatcher()
    ProviderNotificationGateway(dispatcher).dispatch(transition())
    payload = dispatcher.calls[0][1]["structured_payload"]

    assert payload == {
        "kind": "provider_lifecycle_alert",
        "provider_id": "openai",
        "code": "RUNTIME_HEALTH_FAILED",
        "transition_state": "OPEN",
        "severity": "critical",
        "effective_health": "FAILED",
        "evidence_at": "2026-10-08T03:45:00+00:00",
        "evaluated_at": "2026-10-08T03:45:00+00:00",
        "research_only": True,
        "data_admission": "NOT_EVALUATED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def test_content_is_single_line_sanitized_per_field():
    dispatcher = FakeDispatcher()
    ProviderNotificationGateway(dispatcher).dispatch(
        transition(message="first line\nsecond line")
    )
    content = dispatcher.calls[0][0]
    assert "Detail: first line second line" in content


def test_dispatch_failure_is_captured_without_raising_or_mutating_transition():
    original = transition()
    dispatcher = FakeDispatcher(error=RuntimeError("secret-bearing raw error"))
    result = ProviderNotificationGateway(dispatcher).dispatch(original)

    assert result.transition is original
    assert result.attempted is True
    assert result.dispatched is False
    assert result.success is False
    assert result.status == "dispatch_exception"
    assert result.error_code == "dispatcher_exception:RuntimeError"
    assert "secret-bearing" not in result.error_code
    assert result.retryable is True


def test_invalid_dispatch_result_fails_closed():
    result = ProviderNotificationGateway(InvalidDispatcher()).dispatch(transition())
    assert result.success is False
    assert result.status == "invalid_dispatch_result"
    assert result.retryable is True


def test_unknown_dispatch_status_is_rejected_without_persisting_raw_status():
    result = ProviderNotificationGateway(
        FakeDispatcher(FakeDispatchResult(False, False, "secret raw status"))
    ).dispatch(transition())
    assert result.status == "invalid_dispatch_result"
    assert result.error_code == "invalid_dispatch_result"
    assert "secret" not in result.status


@pytest.mark.parametrize(
    "status",
    ["noise_suppressed", "no_channel"],
)
def test_suppressed_or_unconfigured_delivery_is_not_retryable(status):
    result = ProviderNotificationGateway(
        FakeDispatcher(FakeDispatchResult(False, False, status))
    ).dispatch(transition())
    assert result.success is False
    assert result.status == status
    assert result.retryable is False


def test_all_failed_is_retryable():
    result = ProviderNotificationGateway(
        FakeDispatcher(FakeDispatchResult(True, False, "all_failed"))
    ).dispatch(transition())
    assert result.success is False
    assert result.status == "all_failed"
    assert result.retryable is True


def test_notification_result_does_not_change_governance_fields():
    result = ProviderNotificationGateway(
        FakeDispatcher(FakeDispatchResult(True, False, "all_failed"))
    ).dispatch(transition())
    assert result.success is False
    assert result.transition.research_only is True
    assert result.transition.data_admission == "NOT_EVALUATED"
    assert result.transition.radar_admission == "BLOCKED"
    assert result.transition.live_trade is False


def test_dispatch_many_preserves_transition_order():
    first = transition()
    second = transition(
        state=ProviderAlertTransitionState.RESOLVED,
        severity=GuardSeverity.WARNING,
    )
    results = ProviderNotificationGateway(FakeDispatcher()).dispatch_many(
        [first, second]
    )
    assert [item.transition for item in results] == [first, second]


def test_dispatch_rejects_wrong_type():
    with pytest.raises(TypeError, match="ProviderAlertTransition"):
        ProviderNotificationGateway(FakeDispatcher()).dispatch(object())


def test_gateway_requires_dispatcher():
    with pytest.raises(ValueError, match="dispatcher is required"):
        ProviderNotificationGateway(None)


def test_dedup_key_is_stable_for_same_transition():
    dispatcher = FakeDispatcher()
    gateway = ProviderNotificationGateway(dispatcher)
    item = transition()
    gateway.dispatch(item)
    gateway.dispatch(item)
    first = dispatcher.calls[0][1]["dedup_key"]
    second = dispatcher.calls[1][1]["dedup_key"]
    assert first == second


def test_updated_transition_uses_own_cooldown_bucket():
    dispatcher = FakeDispatcher()
    ProviderNotificationGateway(dispatcher).dispatch(
        transition(state=ProviderAlertTransitionState.UPDATED)
    )
    assert dispatcher.calls[0][1]["cooldown_key"].endswith(":UPDATED")
