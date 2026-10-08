from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.services.provider_lifecycle import (
    GuardSeverity,
    ProviderAlertTransition,
    ProviderAlertTransitionState,
    ProviderHealthState,
    ProviderNotificationGateway,
    ProviderNotificationPolicyError,
    format_provider_notification,
)


T0 = datetime(2026, 10, 8, 0, 10, tzinfo=timezone.utc)


def transition(
    *,
    state=ProviderAlertTransitionState.OPEN,
    severity=GuardSeverity.CRITICAL,
    code="RUNTIME_HEALTH_FAILED",
    message="Provider runtime health is failed.",
    effective_health=ProviderHealthState.FAILED,
    evidence_at=T0,
    evaluated_at=T0,
):
    return ProviderAlertTransition(
        provider_id="openai",
        code=code,
        state=state,
        severity=severity,
        message=message,
        evidence_at=evidence_at,
        evaluated_at=evaluated_at,
        effective_health=effective_health,
        alert_key=f"provider_lifecycle:openai:{code}",
    )


class StubService:
    def __init__(self, result=None, error=None):
        self.result = result or SimpleNamespace(
            dispatched=True,
            success=True,
            status="sent",
            channel_results=[],
        )
        self.error = error
        self.calls = []

    def send_with_results(self, content, **kwargs):
        self.calls.append((content, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


def test_gateway_reuses_existing_alert_route_and_governance_payload():
    service = StubService()
    item = transition()
    dispatch = ProviderNotificationGateway(service).dispatch(item)

    assert dispatch.success is True
    assert dispatch.status == "sent"
    assert len(service.calls) == 1
    content, kwargs = service.calls[0]
    assert "Provider Lifecycle" in content
    assert kwargs["route_type"] == "alert"
    assert kwargs["severity"] == "critical"
    assert kwargs["cooldown_key"].startswith(
        "provider_lifecycle:openai:RUNTIME_HEALTH_FAILED:OPEN:"
    )
    payload = kwargs["structured_payload"]
    assert payload["provider_id"] == "openai"
    assert payload["research_only"] is True
    assert payload["data_admission"] == "NOT_EVALUATED"
    assert payload["radar_admission"] == "BLOCKED"
    assert payload["live_trade"] is False


def test_resolved_transition_preserves_severity_and_separate_cooldown():
    service = StubService()
    opened = transition()
    resolved = transition(
        state=ProviderAlertTransitionState.RESOLVED,
        severity=GuardSeverity.CRITICAL,
        effective_health=ProviderHealthState.UNKNOWN,
    )

    open_dispatch = ProviderNotificationGateway(service).dispatch(opened)
    resolved_dispatch = ProviderNotificationGateway(service).dispatch(resolved)

    assert ":OPEN:" in open_dispatch.cooldown_key
    assert ":RESOLVED:" in resolved_dispatch.cooldown_key
    assert open_dispatch.cooldown_key != resolved_dispatch.cooldown_key
    assert service.calls[1][1]["severity"] == "critical"


def test_later_reopen_gets_new_dedup_and_cooldown_keys():
    service = StubService()
    gateway = ProviderNotificationGateway(service)
    first = gateway.dispatch(transition())
    reopened = gateway.dispatch(
        transition(
            evidence_at=datetime(2026, 10, 8, 0, 11, tzinfo=timezone.utc),
            evaluated_at=datetime(2026, 10, 8, 0, 11, tzinfo=timezone.utc),
        )
    )

    assert reopened.dedup_key != first.dedup_key
    assert reopened.cooldown_key != first.cooldown_key


def test_dedup_key_is_stable_for_same_transition_and_changes_for_message_update():
    service = StubService()
    gateway = ProviderNotificationGateway(service)
    first = gateway.dispatch(transition())
    second = gateway.dispatch(transition())
    updated = gateway.dispatch(
        transition(
            state=ProviderAlertTransitionState.UPDATED,
            message="Provider runtime health remains failed.",
        )
    )

    assert first.dedup_key == second.dedup_key
    assert updated.dedup_key != first.dedup_key


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("research_only", False, "research_only"),
        ("data_admission", "PASS", "Data Admission"),
        ("radar_admission", "PASS", "RADAR_ADMISSION=BLOCKED"),
        ("live_trade", True, "LIVE_TRADE=NO"),
    ],
)
def test_gateway_rejects_governance_violation(field_name, value, message):
    item = replace(transition(), **{field_name: value})
    with pytest.raises(ProviderNotificationPolicyError, match=message):
        ProviderNotificationGateway(StubService()).dispatch(item)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("provider_id", "openai\nsecret"),
        ("provider_id", "OpenAI"),
        ("code", "RUNTIME HEALTH FAILED"),
        ("code", "runtime_health_failed"),
    ],
)
def test_gateway_rejects_unsafe_provider_or_code_identity(field_name, value):
    item = replace(transition(), **{field_name: value})
    with pytest.raises(
        ProviderNotificationPolicyError,
        match="unsupported identity characters",
    ):
        ProviderNotificationGateway(StubService()).dispatch(item)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("state", "OPEN", "transition.state"),
        ("severity", "CRITICAL", "transition.severity"),
        ("effective_health", "FAILED", "transition.effective_health"),
    ],
)
def test_gateway_rejects_non_enum_transition_contracts(
    field_name,
    value,
    message,
):
    item = replace(transition(), **{field_name: value})
    with pytest.raises(ProviderNotificationPolicyError, match=message):
        ProviderNotificationGateway(StubService()).dispatch(item)


def test_gateway_rejects_forged_alert_key():
    item = replace(transition(), alert_key="provider_lifecycle:other:code")
    with pytest.raises(
        ProviderNotificationPolicyError,
        match="alert_key does not match",
    ):
        ProviderNotificationGateway(StubService()).dispatch(item)


def test_gateway_rejects_multiline_or_unbounded_transition_message():
    gateway = ProviderNotificationGateway(StubService())
    with pytest.raises(
        ProviderNotificationPolicyError,
        match="single line up to 240",
    ):
        gateway.dispatch(replace(transition(), message="line1\nline2"))
    with pytest.raises(
        ProviderNotificationPolicyError,
        match="single line up to 240",
    ):
        gateway.dispatch(replace(transition(), message="x" * 241))


def test_gateway_rejects_time_reversal():
    item = replace(
        transition(),
        evaluated_at=datetime(2026, 10, 8, 0, 9, tzinfo=timezone.utc),
    )
    with pytest.raises(
        ProviderNotificationPolicyError,
        match="evaluated_at must not be before evidence_at",
    ):
        ProviderNotificationGateway(StubService()).dispatch(item)


def test_delivery_exception_returns_type_only_and_does_not_leak_message():
    secret = "secret-token-123"
    service = StubService(error=RuntimeError(secret))
    dispatch = ProviderNotificationGateway(service).dispatch(transition())

    assert dispatch.attempted is True
    assert dispatch.success is False
    assert dispatch.status == "exception"
    assert dispatch.error_type == "RuntimeError"
    assert secret not in repr(dispatch)


def test_channel_diagnostics_are_reduced_to_safe_fields():
    result = SimpleNamespace(
        dispatched=True,
        success=False,
        status="all_failed",
        channel_results=[
            SimpleNamespace(
                channel="slack",
                success=False,
                error_code="send_failed",
                retryable=True,
                latency_ms=123,
                diagnostics="raw secret diagnostics",
            )
        ],
    )
    dispatch = ProviderNotificationGateway(
        StubService(result=result)
    ).dispatch(transition())

    assert dispatch.success is False
    assert dispatch.channel_results[0].channel == "slack"
    assert dispatch.channel_results[0].error_code == "send_failed"
    assert dispatch.channel_results[0].retryable is True
    assert dispatch.channel_results[0].latency_ms == 123
    assert "raw secret diagnostics" not in repr(dispatch)


def test_free_form_dispatch_diagnostics_are_not_retained():
    result = SimpleNamespace(
        dispatched=True,
        success=False,
        status="raw status with secret",
        channel_results=[
            SimpleNamespace(
                channel="channel with secret",
                success=False,
                error_code="raw error with secret",
                retryable=True,
                latency_ms=10,
            )
        ],
    )
    dispatch = ProviderNotificationGateway(
        StubService(result=result)
    ).dispatch(transition())

    assert dispatch.status == "unknown"
    assert dispatch.channel_results[0].channel == "unknown"
    assert dispatch.channel_results[0].error_code is None
    assert "secret" not in repr(dispatch)


def test_token_shaped_unknown_dispatch_diagnostics_are_not_retained():
    result = SimpleNamespace(
        dispatched=True,
        success=False,
        status="sk_secret_status_123",
        channel_results=[
            SimpleNamespace(
                channel="sk_secret_channel_123",
                success=False,
                error_code="sk_secret_error_123",
                retryable=False,
                latency_ms=5,
            )
        ],
    )
    dispatch = ProviderNotificationGateway(
        StubService(result=result)
    ).dispatch(transition())

    assert dispatch.status == "unknown"
    assert dispatch.channel_results[0].channel == "unknown"
    assert dispatch.channel_results[0].error_code is None
    assert "sk_secret" not in repr(dispatch)


def test_non_boolean_dispatch_flags_fail_closed():
    result = SimpleNamespace(
        dispatched="true",
        success="false",
        status="sent",
        channel_results=[
            SimpleNamespace(
                channel="email",
                success="true",
                error_code=None,
                retryable="false",
                latency_ms=10,
            )
        ],
    )
    dispatch = ProviderNotificationGateway(
        StubService(result=result)
    ).dispatch(transition())

    assert dispatch.attempted is False
    assert dispatch.success is False
    assert dispatch.channel_results[0].success is False
    assert dispatch.channel_results[0].retryable is False


def test_malformed_channel_results_collection_is_dropped_fail_closed():
    result = SimpleNamespace(
        dispatched=True,
        success=True,
        status="sent",
        channel_results="not-a-list",
    )
    dispatch = ProviderNotificationGateway(
        StubService(result=result)
    ).dispatch(transition())

    assert dispatch.success is True
    assert dispatch.channel_results == ()


def test_bad_channel_latency_is_dropped_instead_of_normalized():
    result = SimpleNamespace(
        dispatched=True,
        success=False,
        status="all_failed",
        channel_results=[
            SimpleNamespace(
                channel="email",
                success=False,
                error_code="send_failed",
                retryable=True,
                latency_ms=-1,
            )
        ],
    )
    dispatch = ProviderNotificationGateway(
        StubService(result=result)
    ).dispatch(transition())
    assert dispatch.channel_results[0].latency_ms is None


def test_formatted_notification_is_research_only_and_contains_no_execution_language():
    content = format_provider_notification(transition())
    assert "Research-only" in content
    assert "Data Admission is not evaluated" in content
    assert "Radar admission remains BLOCKED" in content
    assert "LIVE_TRADE remains NO" in content


def test_gateway_does_not_call_service_for_invalid_transition():
    service = StubService()
    item = replace(transition(), live_trade=True)
    with pytest.raises(ProviderNotificationPolicyError):
        ProviderNotificationGateway(service).dispatch(item)
    assert service.calls == []
