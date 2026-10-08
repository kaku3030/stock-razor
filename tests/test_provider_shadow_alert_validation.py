from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import pytest

from src.services.provider_lifecycle import (
    ProviderHealthState,
    ProviderLifecycleRecord,
    ProviderRole,
    ProviderShadowAlertValidator,
    RuntimeProviderSnapshot,
    StaleProviderAlertEvidenceError,
)


T0 = datetime(2026, 10, 8, 0, 10, tzinfo=timezone.utc)


def snapshot(
    *,
    health=ProviderHealthState.UNKNOWN,
    observed_at=T0,
    **record_overrides,
):
    return RuntimeProviderSnapshot(
        record=ProviderLifecycleRecord(
            provider_id="openai",
            role=ProviderRole.AI,
            market_scope=("GLOBAL",),
            health_state=health,
            **record_overrides,
        ),
        field_provenance=MappingProxyType({}),
        observed_at=observed_at,
        evidence_count=1,
    )


def test_shadow_failed_provider_builds_real_gateway_plan_without_delivery():
    result = ProviderShadowAlertValidator().evaluate(
        snapshot(health=ProviderHealthState.FAILED),
        now=T0,
    )

    assert result.validation_status == "VALIDATED"
    assert result.actual_notification_count == 0
    assert result.research_only is True
    assert result.data_admission == "NOT_EVALUATED"
    assert result.radar_admission == "BLOCKED"
    assert result.live_trade is False

    assert len(result.evaluation.transitions) == 1
    assert len(result.notification_plans) == 1
    assert len(result.dispatches) == 1

    plan = result.notification_plans[0]
    dispatch = result.dispatches[0]
    assert plan.route_type == "alert"
    assert plan.severity == "critical"
    assert ":OPEN:" in plan.cooldown_key
    assert "Provider Lifecycle" in plan.content
    assert plan.structured_payload["research_only"] is True
    assert plan.structured_payload["radar_admission"] == "BLOCKED"
    assert plan.structured_payload["live_trade"] is False

    assert dispatch.attempted is False
    assert dispatch.success is False
    assert dispatch.status == "shadow_only"
    assert dispatch.dedup_key == plan.dedup_key
    assert dispatch.cooldown_key == plan.cooldown_key


def test_shadow_repeated_identical_state_emits_no_second_plan():
    validator = ProviderShadowAlertValidator()
    first = validator.evaluate(
        snapshot(health=ProviderHealthState.DEGRADED),
        now=T0,
    )
    second = validator.evaluate(
        snapshot(
            health=ProviderHealthState.DEGRADED,
            observed_at=T0 + timedelta(seconds=1),
        ),
        now=T0 + timedelta(seconds=1),
    )

    assert len(first.notification_plans) == 1
    assert second.evaluation.transitions == ()
    assert second.notification_plans == ()
    assert second.dispatches == ()


def test_shadow_recovery_builds_resolved_plan_with_originating_severity():
    validator = ProviderShadowAlertValidator()
    opened = validator.evaluate(
        snapshot(health=ProviderHealthState.FAILED),
        now=T0,
    )
    recovered = validator.evaluate(
        snapshot(
            health=ProviderHealthState.UNKNOWN,
            observed_at=T0 + timedelta(seconds=1),
        ),
        now=T0 + timedelta(seconds=1),
    )

    assert opened.notification_plans[0].severity == "critical"
    assert len(recovered.notification_plans) == 1
    plan = recovered.notification_plans[0]
    assert plan.structured_payload["transition_state"] == "RESOLVED"
    assert plan.severity == "critical"
    assert ":RESOLVED:" in plan.cooldown_key
    assert plan.cooldown_key != opened.notification_plans[0].cooldown_key


def test_shadow_specific_quota_alert_does_not_duplicate_generic_exhausted():
    result = ProviderShadowAlertValidator().evaluate(
        snapshot(
            health=ProviderHealthState.EXHAUSTED,
            billing_status="INSUFFICIENT_QUOTA",
        ),
        now=T0,
    )

    assert [item.code for item in result.evaluation.transitions] == [
        "BILLING_STATUS_EXHAUSTED"
    ]
    assert len(result.notification_plans) == 1
    assert "BILLING_STATUS_EXHAUSTED" in result.notification_plans[0].content
    assert "RUNTIME_HEALTH_EXHAUSTED" not in result.notification_plans[0].content


def test_shadow_no_alert_state_produces_no_notification_plan():
    result = ProviderShadowAlertValidator().evaluate(
        snapshot(health=ProviderHealthState.UNKNOWN),
        now=T0,
    )
    assert result.evaluation.transitions == ()
    assert result.notification_plans == ()
    assert result.dispatches == ()
    assert result.actual_notification_count == 0


def test_shadow_stale_evidence_is_rejected_by_real_alert_engine():
    validator = ProviderShadowAlertValidator()
    validator.evaluate(
        snapshot(
            health=ProviderHealthState.FAILED,
            observed_at=T0 + timedelta(seconds=10),
        ),
        now=T0 + timedelta(seconds=10),
    )
    with pytest.raises(StaleProviderAlertEvidenceError):
        validator.evaluate(
            snapshot(
                health=ProviderHealthState.UNKNOWN,
                observed_at=T0,
            ),
            now=T0 + timedelta(seconds=11),
        )


def test_shadow_plan_uses_supported_notification_severity():
    result = ProviderShadowAlertValidator().evaluate(
        snapshot(health=ProviderHealthState.DEGRADED),
        now=T0,
    )
    assert result.notification_plans[0].severity == "warning"


def test_shadow_structured_payload_is_read_only_copy():
    result = ProviderShadowAlertValidator().evaluate(
        snapshot(health=ProviderHealthState.RATE_LIMITED),
        now=T0,
    )
    payload = result.notification_plans[0].structured_payload
    with pytest.raises(TypeError):
        payload["live_trade"] = True


def test_shadow_time_based_guard_re_evaluation_uses_same_engine_state():
    validator = ProviderShadowAlertValidator()
    expiry = T0 + timedelta(days=10)
    first = validator.evaluate(
        snapshot(
            credential_expiry=expiry,
            observed_at=T0,
        ),
        now=T0,
    )
    later = validator.evaluate(
        snapshot(
            credential_expiry=expiry,
            observed_at=T0,
        ),
        now=T0 + timedelta(days=4),
    )

    assert [plan.structured_payload["code"] for plan in first.notification_plans] == [
        "CREDENTIAL_EXPIRY_14D"
    ]
    assert [plan.structured_payload["transition_state"] for plan in later.notification_plans] == [
        "RESOLVED",
        "OPEN",
    ]
    assert {
        plan.structured_payload["code"] for plan in later.notification_plans
    } == {
        "CREDENTIAL_EXPIRY_14D",
        "CREDENTIAL_EXPIRY_7D",
    }
