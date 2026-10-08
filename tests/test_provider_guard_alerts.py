from datetime import datetime, timezone

import pytest

from src.services.provider_lifecycle import (
    GuardSeverity,
    ProviderAlert,
    ProviderGuardAlertEngine,
    ProviderGuardAssessment,
    ProviderGuardNotification,
    ProviderHealthState,
    ProviderRuntimeObserver,
    EvidenceProvenance,
    ObservedProviderValue,
    ProviderRuntimeObservation,
    NotificationServiceProviderGuardSink,
    format_provider_guard_notification,
    provider_guard_structured_payload,
)


NOW = datetime(2026, 10, 8, 1, 45, tzinfo=timezone.utc)


def snapshot(provider_id="openai", health=ProviderHealthState.UNKNOWN):
    observer = ProviderRuntimeObserver()
    return observer.ingest(
        ProviderRuntimeObservation(
            provider_id=provider_id,
            fields={
                "health_state": ObservedProviderValue(
                    value=health,
                    provenance=EvidenceProvenance(
                        observed_at=NOW,
                        source="test",
                        runtime_id="runtime-1",
                        repo_sha="a" * 40,
                    ),
                )
            },
        )
    )


def assessment(
    provider_id="openai",
    health=ProviderHealthState.UNKNOWN,
    alerts=(),
    *,
    user_approval_required=False,
    auto_spend_permitted=False,
    projected_exhaustion_at=None,
):
    return ProviderGuardAssessment(
        provider_id=provider_id,
        effective_health=health,
        alerts=tuple(alerts),
        projected_exhaustion_at=projected_exhaustion_at,
        auto_spend_permitted=auto_spend_permitted,
        user_approval_required=user_approval_required,
    )


def test_baseline_unknown_without_alerts_is_quiet():
    engine = ProviderGuardAlertEngine()
    assert engine.evaluate(snapshot(), assessment()) == ()


def test_direct_degraded_health_emits_warning_even_without_explicit_alert():
    engine = ProviderGuardAlertEngine()
    events = engine.evaluate(
        snapshot(health=ProviderHealthState.DEGRADED),
        assessment(health=ProviderHealthState.DEGRADED),
    )
    assert len(events) == 1
    event = events[0]
    assert event.transition == "ACTIVE"
    assert event.severity is GuardSeverity.WARNING
    assert event.alert_codes == ("PROVIDER_HEALTH_DEGRADED",)
    assert event.radar_admission == "UNCHANGED"
    assert event.trading_admission == "UNCHANGED"
    assert event.live_trade is False


def test_same_guard_state_is_not_emitted_twice():
    engine = ProviderGuardAlertEngine()
    snap = snapshot(health=ProviderHealthState.DEGRADED)
    assess = assessment(health=ProviderHealthState.DEGRADED)
    assert len(engine.evaluate(snap, assess)) == 1
    assert engine.evaluate(snap, assess) == ()


def test_escalation_emits_changed_transition():
    engine = ProviderGuardAlertEngine()
    engine.evaluate(
        snapshot(health=ProviderHealthState.DEGRADED),
        assessment(health=ProviderHealthState.DEGRADED),
    )
    events = engine.evaluate(
        snapshot(health=ProviderHealthState.FAILED),
        assessment(health=ProviderHealthState.FAILED),
    )
    assert len(events) == 1
    assert events[0].transition == "CHANGED"
    assert events[0].severity is GuardSeverity.CRITICAL
    assert events[0].alert_codes == ("PROVIDER_HEALTH_FAILED",)


def test_explicit_alerts_are_aggregated_with_highest_severity():
    engine = ProviderGuardAlertEngine()
    events = engine.evaluate(
        snapshot(),
        assessment(
            alerts=(
                ProviderAlert(
                    GuardSeverity.INFO,
                    "QUOTA_BELOW_25_PERCENT",
                    "Provider quota remaining is below 25%.",
                ),
                ProviderAlert(
                    GuardSeverity.CRITICAL,
                    "COST_ANOMALY",
                    "Provider cost anomaly is active.",
                ),
            ),
        ),
    )
    event = events[0]
    assert event.severity is GuardSeverity.CRITICAL
    assert event.alert_codes == (
        "COST_ANOMALY",
        "QUOTA_BELOW_25_PERCENT",
    )


def test_clear_event_does_not_claim_provider_healthy():
    engine = ProviderGuardAlertEngine()
    engine.evaluate(
        snapshot(health=ProviderHealthState.DEGRADED),
        assessment(health=ProviderHealthState.DEGRADED),
    )
    events = engine.evaluate(
        snapshot(health=ProviderHealthState.UNKNOWN),
        assessment(health=ProviderHealthState.UNKNOWN),
    )
    assert len(events) == 1
    event = events[0]
    assert event.transition == "CLEARED"
    assert event.severity is GuardSeverity.INFO
    assert event.effective_health is ProviderHealthState.UNKNOWN
    assert event.alert_codes == ("PROVIDER_GUARD_ALERTS_CLEARED",)
    text = format_provider_guard_notification(event)
    assert "does not imply Data, Radar, or Trading admission" in text
    assert "HEALTHY" not in text


def test_benign_unknown_to_healthy_without_prior_problem_stays_quiet():
    engine = ProviderGuardAlertEngine()
    assert engine.evaluate(snapshot(), assessment()) == ()
    assert engine.evaluate(
        snapshot(health=ProviderHealthState.HEALTHY),
        assessment(health=ProviderHealthState.HEALTHY),
    ) == ()


def test_user_approval_change_is_meaningful_state_change():
    engine = ProviderGuardAlertEngine()
    alert = ProviderAlert(
        GuardSeverity.CRITICAL,
        "AUTO_RECHARGE_ENABLED",
        "Auto recharge is enabled externally.",
    )
    first = engine.evaluate(
        snapshot(),
        assessment(alerts=(alert,), user_approval_required=False),
    )
    second = engine.evaluate(
        snapshot(),
        assessment(alerts=(alert,), user_approval_required=True),
    )
    assert first[0].transition == "ACTIVE"
    assert second[0].transition == "CHANGED"
    assert second[0].user_approval_required is True


def test_provider_mismatch_is_rejected():
    engine = ProviderGuardAlertEngine()
    with pytest.raises(ValueError, match="does not match"):
        engine.evaluate(
            snapshot(provider_id="openai"),
            assessment(provider_id="anthropic"),
        )


def test_auto_spend_permission_is_rejected_fail_closed():
    engine = ProviderGuardAlertEngine()
    with pytest.raises(ValueError, match="automatic spend"):
        engine.evaluate(
            snapshot(),
            assessment(auto_spend_permitted=True),
        )


class FakeNotificationService:
    def __init__(self):
        self.calls = []

    def send_with_results(self, content, **kwargs):
        self.calls.append((content, kwargs))
        return {"status": "sent"}


class FailingNotificationService:
    def send_with_results(self, content, **kwargs):
        raise RuntimeError("secret-bearing provider failure text")


def test_notification_sink_reuses_alert_route_and_noise_keys():
    service = FakeNotificationService()
    sink = NotificationServiceProviderGuardSink(service)
    event = ProviderGuardNotification(
        provider_id="openai",
        transition="ACTIVE",
        severity=GuardSeverity.CRITICAL,
        effective_health=ProviderHealthState.EXHAUSTED,
        alert_codes=("BILLING_STATUS_EXHAUSTED",),
        messages=("Provider billing status is exhausted.",),
        observed_at=NOW,
        decision_criticality="AI_ENRICHMENT",
        user_approval_required=False,
        auto_spend_permitted=False,
        projected_exhaustion_at=None,
        state_key="EXHAUSTED:BILLING_STATUS_EXHAUSTED:NO_APPROVAL",
    )

    sink(event)

    assert sink.last_error is None
    assert len(service.calls) == 1
    content, kwargs = service.calls[0]
    assert "Provider Guard" in content
    assert kwargs["route_type"] == "alert"
    assert kwargs["severity"] == "critical"
    assert kwargs["dedup_key"].startswith("provider_guard:openai:ACTIVE:")
    assert kwargs["cooldown_key"].startswith("provider_guard:openai:")
    structured = kwargs["structured_payload"]
    assert structured["radar_admission"] == "UNCHANGED"
    assert structured["trading_admission"] == "UNCHANGED"
    assert structured["live_trade"] is False
    assert structured["auto_spend_permitted"] is False
    assert structured["research_only"] is True


def test_notification_sink_records_error_type_not_raw_exception_message():
    sink = NotificationServiceProviderGuardSink(FailingNotificationService())
    event = ProviderGuardNotification(
        provider_id="tavily",
        transition="ACTIVE",
        severity=GuardSeverity.WARNING,
        effective_health=ProviderHealthState.RATE_LIMITED,
        alert_codes=("PROVIDER_HEALTH_RATE_LIMITED",),
        messages=("Provider effective health is rate_limited.",),
        observed_at=NOW,
        decision_criticality="ENRICHMENT",
        user_approval_required=False,
        auto_spend_permitted=False,
        projected_exhaustion_at=None,
        state_key="RATE_LIMITED:PROVIDER_HEALTH_RATE_LIMITED:NO_APPROVAL",
    )
    sink(event)
    assert sink.last_dispatch is None
    assert sink.last_error == "RuntimeError"
    assert "secret-bearing" not in sink.last_error


def test_structured_payload_never_changes_admission_or_live_trade():
    event = ProviderGuardNotification(
        provider_id="anthropic",
        transition="ACTIVE",
        severity=GuardSeverity.CRITICAL,
        effective_health=ProviderHealthState.EXPIRED,
        alert_codes=("CREDENTIAL_EXPIRED",),
        messages=("Provider credential is expired.",),
        observed_at=NOW,
        decision_criticality="AI_ENRICHMENT",
        user_approval_required=False,
        auto_spend_permitted=False,
        projected_exhaustion_at=None,
        state_key="EXPIRED:CREDENTIAL_EXPIRED:NO_APPROVAL",
    )
    payload = provider_guard_structured_payload(event)
    assert payload["radar_admission"] == "UNCHANGED"
    assert payload["trading_admission"] == "UNCHANGED"
    assert payload["live_trade"] is False
    assert payload["auto_spend_permitted"] is False


def test_notification_contract_requires_reasoned_active_state():
    with pytest.raises(ValueError, match="require alert codes"):
        ProviderGuardNotification(
            provider_id="openai",
            transition="ACTIVE",
            severity=GuardSeverity.CRITICAL,
            effective_health=ProviderHealthState.EXHAUSTED,
            alert_codes=(),
            messages=(),
            observed_at=NOW,
            decision_criticality="AI_ENRICHMENT",
            user_approval_required=False,
            auto_spend_permitted=False,
            projected_exhaustion_at=None,
            state_key="EXHAUSTED:NONE:NO_APPROVAL",
        )


def test_notification_contract_rejects_misaligned_codes_and_messages():
    with pytest.raises(ValueError, match="same length"):
        ProviderGuardNotification(
            provider_id="openai",
            transition="ACTIVE",
            severity=GuardSeverity.CRITICAL,
            effective_health=ProviderHealthState.EXHAUSTED,
            alert_codes=("A",),
            messages=(),
            observed_at=NOW,
            decision_criticality="AI_ENRICHMENT",
            user_approval_required=False,
            auto_spend_permitted=False,
            projected_exhaustion_at=None,
            state_key="EXHAUSTED:A:NO_APPROVAL",
        )


def test_cleared_notification_must_be_info():
    with pytest.raises(ValueError, match="must be INFO"):
        ProviderGuardNotification(
            provider_id="openai",
            transition="CLEARED",
            severity=GuardSeverity.WARNING,
            effective_health=ProviderHealthState.UNKNOWN,
            alert_codes=("PROVIDER_GUARD_ALERTS_CLEARED",),
            messages=("cleared",),
            observed_at=NOW,
            decision_criticality="AI_ENRICHMENT",
            user_approval_required=False,
            auto_spend_permitted=False,
            projected_exhaustion_at=None,
            state_key="UNKNOWN:PROVIDER_GUARD_ALERTS_CLEARED:NO_APPROVAL",
        )


def test_notification_contract_requires_state_key():
    with pytest.raises(ValueError, match="state_key"):
        ProviderGuardNotification(
            provider_id="openai",
            transition="ACTIVE",
            severity=GuardSeverity.CRITICAL,
            effective_health=ProviderHealthState.EXHAUSTED,
            alert_codes=("A",),
            messages=("a",),
            observed_at=NOW,
            decision_criticality="AI_ENRICHMENT",
            user_approval_required=False,
            auto_spend_permitted=False,
            projected_exhaustion_at=None,
            state_key=" ",
        )


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("radar_admission", "PASS"),
        ("trading_admission", "PASS"),
        ("live_trade", True),
        ("auto_spend_permitted", True),
    ],
)
def test_notification_contract_rejects_permission_escalation(field_name, value):
    kwargs = {
        "provider_id": "aws",
        "transition": "ACTIVE",
        "severity": GuardSeverity.CRITICAL,
        "effective_health": ProviderHealthState.FAILED,
        "alert_codes": ("PROVIDER_HEALTH_FAILED",),
        "messages": ("Provider effective health is failed.",),
        "observed_at": NOW,
        "decision_criticality": "INFRA_CRITICAL",
        "user_approval_required": False,
        "auto_spend_permitted": False,
        "projected_exhaustion_at": None,
        "state_key": "FAILED:PROVIDER_HEALTH_FAILED:NO_APPROVAL",
        "radar_admission": "UNCHANGED",
        "trading_admission": "UNCHANGED",
        "live_trade": False,
    }
    kwargs[field_name] = value
    with pytest.raises(ValueError):
        ProviderGuardNotification(**kwargs)
