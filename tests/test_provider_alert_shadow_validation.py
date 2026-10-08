from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import pytest

from src.services.provider_lifecycle import (
    ProviderAlertShadowValidator,
    ProviderHealthState,
    ProviderLifecycleRecord,
    ProviderRole,
    RuntimeProviderSnapshot,
    StaleProviderAlertEvidenceError,
)


T0 = datetime(2026, 10, 8, 4, 15, tzinfo=timezone.utc)


def snapshot(
    *,
    provider_id="openai",
    role=ProviderRole.AI,
    health=ProviderHealthState.UNKNOWN,
    observed_at=T0,
    **overrides,
):
    record = ProviderLifecycleRecord(
        provider_id=provider_id,
        role=role,
        market_scope=("GLOBAL",),
        health_state=health,
        **overrides,
    )
    return RuntimeProviderSnapshot(
        record=record,
        field_provenance=MappingProxyType({}),
        observed_at=observed_at,
        evidence_count=1,
    )


def test_shadow_observe_records_would_be_alert_without_delivery():
    validator = ProviderAlertShadowValidator()
    batch = validator.observe(
        snapshot(health=ProviderHealthState.DEGRADED),
        now=T0,
    )

    assert len(batch.events) == 1
    event = batch.events[0]
    assert event.provider_id == "openai"
    assert event.code == "RUNTIME_HEALTH_DEGRADED"
    assert event.transition_state == "OPEN"
    assert event.route_type == "alert"
    assert event.shadow_only is True
    assert event.delivery_attempted is False
    assert event.research_only is True
    assert event.data_admission == "NOT_EVALUATED"
    assert event.radar_admission == "BLOCKED"
    assert event.live_trade is False


def test_repeated_identical_state_produces_no_duplicate_shadow_event():
    validator = ProviderAlertShadowValidator()
    validator.observe(
        snapshot(health=ProviderHealthState.DEGRADED),
        now=T0,
    )
    second = validator.observe(
        snapshot(
            health=ProviderHealthState.DEGRADED,
            observed_at=T0 + timedelta(seconds=1),
        ),
        now=T0 + timedelta(seconds=1),
    )

    assert second.events == ()
    assert len(validator.journal()) == 1
    assert validator.summary().snapshot_count == 2


def test_recovery_records_resolved_event_and_completed_cycle():
    validator = ProviderAlertShadowValidator()
    validator.observe(
        snapshot(health=ProviderHealthState.RATE_LIMITED),
        now=T0,
    )
    recovered = validator.observe(
        snapshot(
            health=ProviderHealthState.UNKNOWN,
            observed_at=T0 + timedelta(seconds=1),
        ),
        now=T0 + timedelta(seconds=1),
    )

    assert [event.transition_state for event in recovered.events] == ["RESOLVED"]
    summary = validator.summary()
    assert summary.open_count == 1
    assert summary.resolved_count == 1
    assert summary.completed_cycle_count == 1
    assert summary.active_alert_count == 0


def test_shadow_summary_never_permits_notification_activation():
    validator = ProviderAlertShadowValidator()
    before = validator.summary()
    validator.observe(
        snapshot(health=ProviderHealthState.FAILED),
        now=T0,
    )
    after = validator.summary()

    assert before.notification_activation_permitted is False
    assert after.notification_activation_permitted is False
    assert before.shadow_status == "COLLECTING"
    assert after.shadow_status == "EVIDENCE_AVAILABLE"
    assert after.radar_admission == "BLOCKED"
    assert after.live_trade is False


def test_stale_snapshot_does_not_mutate_shadow_journal_or_counts():
    validator = ProviderAlertShadowValidator()
    validator.observe(
        snapshot(
            health=ProviderHealthState.FAILED,
            observed_at=T0 + timedelta(seconds=10),
        ),
        now=T0 + timedelta(seconds=10),
    )
    before = validator.summary()

    with pytest.raises(StaleProviderAlertEvidenceError):
        validator.observe(
            snapshot(
                health=ProviderHealthState.UNKNOWN,
                observed_at=T0,
            ),
            now=T0 + timedelta(seconds=11),
        )

    assert validator.summary() == before
    assert len(validator.journal()) == 1


def test_time_reversal_does_not_mutate_shadow_state():
    validator = ProviderAlertShadowValidator()
    with pytest.raises(
        ValueError,
        match="now must not be before snapshot.observed_at",
    ):
        validator.observe(
            snapshot(observed_at=T0 + timedelta(seconds=1)),
            now=T0,
        )
    assert validator.summary().snapshot_count == 0
    assert validator.journal() == ()


def test_same_evidence_can_be_re_evaluated_for_credential_expiry_bands():
    validator = ProviderAlertShadowValidator()
    expiry = T0 + timedelta(days=10)

    first = validator.observe(
        snapshot(credential_expiry=expiry),
        now=T0,
    )
    later = validator.observe(
        snapshot(credential_expiry=expiry),
        now=T0 + timedelta(days=4),
    )

    assert [event.code for event in first.events] == ["CREDENTIAL_EXPIRY_14D"]
    assert [event.transition_state for event in later.events] == [
        "RESOLVED",
        "OPEN",
    ]
    assert [event.code for event in later.events] == [
        "CREDENTIAL_EXPIRY_14D",
        "CREDENTIAL_EXPIRY_7D",
    ]


def test_shadow_event_id_is_deterministic_across_independent_validators():
    first = ProviderAlertShadowValidator().observe(
        snapshot(health=ProviderHealthState.FAILED),
        now=T0,
    ).events[0]
    second = ProviderAlertShadowValidator().observe(
        snapshot(health=ProviderHealthState.FAILED),
        now=T0,
    ).events[0]

    assert first.shadow_event_id == second.shadow_event_id
    assert first.shadow_event_id.startswith("provider-alert-shadow-")


def test_multiple_providers_are_tracked_without_cross_provider_state():
    validator = ProviderAlertShadowValidator()
    validator.observe(
        snapshot(
            provider_id="openai",
            role=ProviderRole.AI,
            health=ProviderHealthState.FAILED,
        ),
        now=T0,
    )
    validator.observe(
        snapshot(
            provider_id="tavily",
            role=ProviderRole.SEARCH,
            health=ProviderHealthState.RATE_LIMITED,
        ),
        now=T0,
    )

    summary = validator.summary()
    assert summary.providers_observed == ("openai", "tavily")
    assert summary.active_alert_count == 2
    assert set(summary.codes_seen) == {
        "RUNTIME_HEALTH_FAILED",
        "RUNTIME_HEALTH_RATE_LIMITED",
    }


def test_shadow_journal_does_not_persist_raw_provider_failure_reason():
    validator = ProviderAlertShadowValidator()
    batch = validator.observe(
        snapshot(
            health=ProviderHealthState.FAILED,
            failure_reason="secret-token-should-never-appear",
        ),
        now=T0,
    )
    event = batch.events[0]
    assert "secret-token" not in event.message
    assert "secret-token" not in repr(event)


def test_shadow_journal_returns_immutable_tuple_snapshot():
    validator = ProviderAlertShadowValidator()
    validator.observe(
        snapshot(health=ProviderHealthState.DEGRADED),
        now=T0,
    )
    journal = validator.journal()
    assert isinstance(journal, tuple)
    with pytest.raises(AttributeError):
        journal.append("bad")


def test_observe_many_preserves_input_order():
    validator = ProviderAlertShadowValidator()
    batches = validator.observe_many([
        (
            snapshot(
                provider_id="openai",
                role=ProviderRole.AI,
                health=ProviderHealthState.FAILED,
                observed_at=T0,
            ),
            T0,
        ),
        (
            snapshot(
                provider_id="tavily",
                role=ProviderRole.SEARCH,
                health=ProviderHealthState.RATE_LIMITED,
                observed_at=T0 + timedelta(seconds=1),
            ),
            T0 + timedelta(seconds=1),
        ),
    ])
    assert [batch.events[0].provider_id for batch in batches] == [
        "openai",
        "tavily",
    ]


def test_wrong_snapshot_type_is_rejected_without_mutation():
    validator = ProviderAlertShadowValidator()
    with pytest.raises(TypeError, match="RuntimeProviderSnapshot"):
        validator.observe(object(), now=T0)
    assert validator.summary().snapshot_count == 0
