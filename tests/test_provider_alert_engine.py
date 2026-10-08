from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import pytest

from src.services.provider_lifecycle import (
    GuardSeverity,
    ProviderAlertEngine,
    ProviderAlertTransitionState,
    ProviderHealthState,
    ProviderLifecycleRecord,
    ProviderRole,
    RuntimeProviderSnapshot,
    StaleProviderAlertEvidenceError,
)


T0 = datetime(2026, 10, 8, 0, 10, tzinfo=timezone.utc)


def snapshot(
    *,
    provider_id="openai",
    role=ProviderRole.AI,
    health=ProviderHealthState.UNKNOWN,
    observed_at=T0,
    **record_overrides,
):
    record = ProviderLifecycleRecord(
        provider_id=provider_id,
        role=role,
        market_scope=("GLOBAL",),
        health_state=health,
        **record_overrides,
    )
    return RuntimeProviderSnapshot(
        record=record,
        field_provenance=MappingProxyType({}),
        observed_at=observed_at,
        evidence_count=1,
    )


def transition_codes(evaluation):
    return [
        (item.state, item.code, item.severity)
        for item in evaluation.transitions
    ]


@pytest.mark.parametrize(
    "health",
    [ProviderHealthState.UNKNOWN, ProviderHealthState.HEALTHY],
)
def test_unknown_and_healthy_do_not_emit_alerts(health):
    evaluation = ProviderAlertEngine().evaluate(
        snapshot(health=health),
        now=T0,
    )
    assert evaluation.transitions == ()
    assert evaluation.active_alerts == ()


@pytest.mark.parametrize(
    ("health", "severity"),
    [
        (ProviderHealthState.WARNING, GuardSeverity.WARNING),
        (ProviderHealthState.DEGRADED, GuardSeverity.WARNING),
        (ProviderHealthState.RATE_LIMITED, GuardSeverity.WARNING),
        (ProviderHealthState.FAILED, GuardSeverity.CRITICAL),
        (ProviderHealthState.EXHAUSTED, GuardSeverity.CRITICAL),
        (ProviderHealthState.EXPIRED, GuardSeverity.CRITICAL),
    ],
)
def test_runtime_health_opens_typed_alert_when_not_specifically_represented(
    health,
    severity,
):
    evaluation = ProviderAlertEngine().evaluate(
        snapshot(health=health),
        now=T0,
    )
    assert transition_codes(evaluation) == [
        (
            ProviderAlertTransitionState.OPEN,
            f"RUNTIME_HEALTH_{health.value}",
            severity,
        )
    ]
    transition = evaluation.transitions[0]
    assert transition.alert_key == (
        f"provider_lifecycle:openai:RUNTIME_HEALTH_{health.value}"
    )
    assert transition.research_only is True
    assert transition.data_admission == "NOT_EVALUATED"
    assert transition.radar_admission == "BLOCKED"
    assert transition.live_trade is False


def test_specific_billing_exhausted_alert_suppresses_duplicate_runtime_alert():
    evaluation = ProviderAlertEngine().evaluate(
        snapshot(
            health=ProviderHealthState.EXHAUSTED,
            billing_status="INSUFFICIENT_QUOTA",
        ),
        now=T0,
    )
    assert transition_codes(evaluation) == [
        (
            ProviderAlertTransitionState.OPEN,
            "BILLING_STATUS_EXHAUSTED",
            GuardSeverity.CRITICAL,
        )
    ]


def test_specific_auth_failure_alert_suppresses_duplicate_runtime_failed_alert():
    evaluation = ProviderAlertEngine().evaluate(
        snapshot(
            health=ProviderHealthState.FAILED,
            credential_status="AUTH_FAILED",
        ),
        now=T0,
    )
    assert transition_codes(evaluation) == [
        (
            ProviderAlertTransitionState.OPEN,
            "CREDENTIAL_STATUS_FAILED",
            GuardSeverity.CRITICAL,
        )
    ]


def test_specific_expired_credential_suppresses_duplicate_runtime_expired_alert():
    evaluation = ProviderAlertEngine().evaluate(
        snapshot(
            health=ProviderHealthState.EXPIRED,
            credential_status="EXPIRED_OR_INVALID",
        ),
        now=T0,
    )
    assert transition_codes(evaluation) == [
        (
            ProviderAlertTransitionState.OPEN,
            "CREDENTIAL_STATUS_EXPIRED",
            GuardSeverity.CRITICAL,
        )
    ]


def test_repeated_identical_alert_state_is_deduplicated():
    engine = ProviderAlertEngine()
    first = engine.evaluate(
        snapshot(health=ProviderHealthState.DEGRADED),
        now=T0,
    )
    second = engine.evaluate(
        snapshot(
            health=ProviderHealthState.DEGRADED,
            observed_at=T0 + timedelta(seconds=1),
        ),
        now=T0 + timedelta(seconds=1),
    )
    assert len(first.transitions) == 1
    assert second.transitions == ()
    assert [alert.code for alert in second.active_alerts] == [
        "RUNTIME_HEALTH_DEGRADED"
    ]


def test_runtime_state_change_resolves_old_and_opens_new_alert():
    engine = ProviderAlertEngine()
    engine.evaluate(
        snapshot(health=ProviderHealthState.DEGRADED),
        now=T0,
    )
    evaluation = engine.evaluate(
        snapshot(
            health=ProviderHealthState.FAILED,
            observed_at=T0 + timedelta(seconds=1),
        ),
        now=T0 + timedelta(seconds=1),
    )
    assert transition_codes(evaluation) == [
        (
            ProviderAlertTransitionState.RESOLVED,
            "RUNTIME_HEALTH_DEGRADED",
            GuardSeverity.WARNING,
        ),
        (
            ProviderAlertTransitionState.OPEN,
            "RUNTIME_HEALTH_FAILED",
            GuardSeverity.CRITICAL,
        ),
    ]


def test_recovery_emits_resolved_once():
    engine = ProviderAlertEngine()
    engine.evaluate(
        snapshot(health=ProviderHealthState.RATE_LIMITED),
        now=T0,
    )
    recovered = engine.evaluate(
        snapshot(
            health=ProviderHealthState.UNKNOWN,
            observed_at=T0 + timedelta(seconds=1),
        ),
        now=T0 + timedelta(seconds=1),
    )
    repeated = engine.evaluate(
        snapshot(
            health=ProviderHealthState.UNKNOWN,
            observed_at=T0 + timedelta(seconds=2),
        ),
        now=T0 + timedelta(seconds=2),
    )
    assert transition_codes(recovered) == [
        (
            ProviderAlertTransitionState.RESOLVED,
            "RUNTIME_HEALTH_RATE_LIMITED",
            GuardSeverity.WARNING,
        )
    ]
    assert repeated.transitions == ()


def test_stale_snapshot_is_rejected_without_rolling_alert_state_back():
    engine = ProviderAlertEngine()
    engine.evaluate(
        snapshot(
            health=ProviderHealthState.FAILED,
            observed_at=T0 + timedelta(seconds=10),
        ),
        now=T0 + timedelta(seconds=10),
    )
    with pytest.raises(StaleProviderAlertEvidenceError):
        engine.evaluate(
            snapshot(
                health=ProviderHealthState.UNKNOWN,
                observed_at=T0,
            ),
            now=T0 + timedelta(seconds=11),
        )
    assert [alert.code for alert in engine.active_alerts("openai")] == [
        "RUNTIME_HEALTH_FAILED"
    ]


def test_same_evidence_can_transition_when_time_based_expiry_band_changes():
    engine = ProviderAlertEngine()
    credential_expiry = T0 + timedelta(days=10)
    first = engine.evaluate(
        snapshot(
            credential_expiry=credential_expiry,
            observed_at=T0,
        ),
        now=T0,
    )
    later = engine.evaluate(
        snapshot(
            credential_expiry=credential_expiry,
            observed_at=T0,
        ),
        now=T0 + timedelta(days=4),
    )
    assert transition_codes(first) == [
        (
            ProviderAlertTransitionState.OPEN,
            "CREDENTIAL_EXPIRY_14D",
            GuardSeverity.INFO,
        )
    ]
    assert transition_codes(later) == [
        (
            ProviderAlertTransitionState.RESOLVED,
            "CREDENTIAL_EXPIRY_14D",
            GuardSeverity.INFO,
        ),
        (
            ProviderAlertTransitionState.OPEN,
            "CREDENTIAL_EXPIRY_7D",
            GuardSeverity.WARNING,
        ),
    ]


def test_auto_recharge_alert_keeps_user_approval_required():
    evaluation = ProviderAlertEngine().evaluate(
        snapshot(auto_recharge_enabled=True),
        now=T0,
    )
    assert transition_codes(evaluation) == [
        (
            ProviderAlertTransitionState.OPEN,
            "AUTO_RECHARGE_ENABLED",
            GuardSeverity.CRITICAL,
        )
    ]
    assert evaluation.assessment.auto_spend_permitted is False
    assert evaluation.assessment.user_approval_required is True


def test_cost_anomaly_uses_existing_guard_assessment_without_runtime_duplicate():
    evaluation = ProviderAlertEngine().evaluate(
        snapshot(cost_anomaly=True),
        now=T0,
    )
    assert transition_codes(evaluation) == [
        (
            ProviderAlertTransitionState.OPEN,
            "COST_ANOMALY",
            GuardSeverity.CRITICAL,
        )
    ]


def test_evaluation_time_before_evidence_is_rejected():
    with pytest.raises(
        ValueError,
        match="now must not be before snapshot.observed_at",
    ):
        ProviderAlertEngine().evaluate(
            snapshot(observed_at=T0 + timedelta(seconds=1)),
            now=T0,
        )


def test_naive_evaluation_time_is_rejected():
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        ProviderAlertEngine().evaluate(
            snapshot(),
            now=datetime(2026, 10, 8, 0, 10),
        )


def test_active_alerts_validates_provider_id():
    engine = ProviderAlertEngine()
    with pytest.raises(ValueError, match="provider_id is required"):
        engine.active_alerts("")
    with pytest.raises(ValueError, match="outer whitespace"):
        engine.active_alerts(" openai ")
