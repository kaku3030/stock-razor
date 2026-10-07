from datetime import datetime, timedelta, timezone

import pytest

from src.services.provider_lifecycle import (
    EvidenceConflictError,
    EvidenceProvenance,
    ObservedProviderValue,
    ProviderHealthState,
    ProviderRuntimeObservation,
    ProviderRuntimeObserver,
    assess_provider,
)


NOW = datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc)


def evidence(value, *, seconds=0, source="runtime", **kwargs):
    return ObservedProviderValue(
        value=value,
        provenance=EvidenceProvenance(
            observed_at=NOW + timedelta(seconds=seconds),
            source=source,
            **kwargs,
        ),
    )


def observation(provider_id="moomoo_opend", **fields):
    return ProviderRuntimeObservation(provider_id=provider_id, fields=fields)


def test_observer_keeps_static_identity_from_registry():
    snapshot = ProviderRuntimeObserver().ingest(
        observation(latency_ms=evidence(12.5))
    )
    assert snapshot.record.provider_id == "moomoo_opend"
    assert snapshot.record.role.value == "PRIMARY"
    assert snapshot.record.market_scope == ("US",)
    assert snapshot.record.fallback_provider == "alpaca"


def test_missing_runtime_fields_remain_unknown_not_zero_or_healthy():
    snapshot = ProviderRuntimeObserver().ingest(
        observation(latency_ms=evidence(12.5))
    )
    assert snapshot.record.health_state is ProviderHealthState.UNKNOWN
    assert snapshot.record.mtd_cost is None
    assert snapshot.record.quota_remaining is None
    assert snapshot.record.credential_status == "UNKNOWN"


def test_field_level_provenance_is_retained():
    snapshot = ProviderRuntimeObserver().ingest(
        observation(
            failure_reason=evidence(
                "HTTP_401",
                source="anthropic-auth-probe",
                runtime_id="cloud-a",
                repo_sha="abc123",
                error_code="HTTP_401",
                evidence_id="probe-7",
            )
        )
    )
    provenance = snapshot.provenance_for("failure_reason")
    assert provenance is not None
    assert provenance.source == "anthropic-auth-probe"
    assert provenance.runtime_id == "cloud-a"
    assert provenance.repo_sha == "abc123"
    assert provenance.error_code == "HTTP_401"
    assert provenance.evidence_id == "probe-7"


def test_newer_evidence_wins_independently_per_field():
    observer = ProviderRuntimeObserver()
    observer.ingest(
        observation(
            latency_ms=evidence(100.0, seconds=1, source="probe-a"),
            freshness_ms=evidence(900.0, seconds=1, source="probe-b"),
        )
    )
    snapshot = observer.ingest(
        observation(latency_ms=evidence(80.0, seconds=2, source="probe-c"))
    )
    assert snapshot.record.latency_ms == 80.0
    assert snapshot.record.freshness_ms == 900.0
    assert snapshot.provenance_for("latency_ms").source == "probe-c"
    assert snapshot.provenance_for("freshness_ms").source == "probe-b"


def test_older_evidence_cannot_roll_field_backward():
    observer = ProviderRuntimeObserver()
    observer.ingest(observation(latency_ms=evidence(80.0, seconds=2)))
    snapshot = observer.ingest(observation(latency_ms=evidence(200.0, seconds=1)))
    assert snapshot.record.latency_ms == 80.0


def test_equal_time_conflict_is_rejected_and_previous_snapshot_survives():
    observer = ProviderRuntimeObserver()
    observer.ingest(observation(latency_ms=evidence(80.0, seconds=1)))
    with pytest.raises(EvidenceConflictError):
        observer.ingest(observation(latency_ms=evidence(81.0, seconds=1)))
    assert observer.snapshot("moomoo_opend").record.latency_ms == 80.0


def test_invalid_candidate_is_transactional():
    observer = ProviderRuntimeObserver()
    observer.ingest(observation(latency_ms=evidence(80.0, seconds=1)))
    with pytest.raises(ValueError, match="quota_remaining must be >= 0"):
        observer.ingest(
            observation(quota_remaining=evidence(-1.0, seconds=2))
        )
    snapshot = observer.snapshot("moomoo_opend")
    assert snapshot.record.latency_ms == 80.0
    assert snapshot.record.quota_remaining is None


def test_observed_at_must_be_timezone_aware():
    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        EvidenceProvenance(
            observed_at=datetime(2026, 10, 8, 1, 0),
            source="probe",
        )


def test_observation_fields_are_frozen_after_validation():
    raw_fields = {"latency_ms": evidence(10.0)}
    runtime_observation = ProviderRuntimeObservation(
        provider_id="moomoo_opend",
        fields=raw_fields,
    )
    raw_fields["latency_ms"] = evidence(999.0, seconds=1)
    assert runtime_observation.fields["latency_ms"].value == 10.0
    with pytest.raises(TypeError):
        runtime_observation.fields["latency_ms"] = evidence(20.0)


@pytest.mark.parametrize(
    "field_name",
    ["provider_id", "role", "market_scope", "decision_criticality", "fallback_provider"],
)
def test_runtime_evidence_cannot_override_static_registry_identity(field_name):
    with pytest.raises(ValueError, match="unsupported runtime evidence field"):
        ProviderRuntimeObservation(
            provider_id="moomoo_opend",
            fields={field_name: evidence("override")},
        )


def test_unknown_provider_is_rejected():
    observer = ProviderRuntimeObserver()
    with pytest.raises(KeyError, match="unknown provider_id"):
        observer.ingest(
            ProviderRuntimeObservation(
                provider_id="unknown-provider",
                fields={"latency_ms": evidence(1.0)},
            )
        )


def test_observed_at_is_not_freshness_evidence():
    snapshot = ProviderRuntimeObserver().ingest(
        observation(latency_ms=evidence(10.0, seconds=10))
    )
    assert snapshot.observed_at == NOW + timedelta(seconds=10)
    assert snapshot.record.freshness_ms is None


def test_health_assessment_stays_separate_but_can_consume_observed_record():
    snapshot = ProviderRuntimeObserver().ingest(
        ProviderRuntimeObservation(
            provider_id="anthropic",
            fields={
                "credential_status": evidence(
                    "EXPIRED_OR_INVALID",
                    source="auth-probe",
                    error_code="HTTP_401",
                )
            },
        )
    )
    assessment = assess_provider(snapshot.record, now=NOW)
    assert assessment.effective_health is ProviderHealthState.EXPIRED


def test_cost_and_quota_evidence_can_come_from_independent_sources():
    observer = ProviderRuntimeObserver()
    observer.ingest(
        ProviderRuntimeObservation(
            provider_id="aws",
            fields={
                "mtd_cost": evidence(12.5, source="cost-explorer"),
            },
        )
    )
    snapshot = observer.ingest(
        ProviderRuntimeObservation(
            provider_id="aws",
            fields={
                "budget_remaining": evidence(87.5, seconds=1, source="budget-api"),
            },
        )
    )
    assert snapshot.record.mtd_cost == 12.5
    assert snapshot.record.budget_remaining == 87.5
    assert snapshot.provenance_for("mtd_cost").source == "cost-explorer"
    assert snapshot.provenance_for("budget_remaining").source == "budget-api"
