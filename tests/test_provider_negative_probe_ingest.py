from datetime import datetime, timezone

import pytest

from src.services.provider_lifecycle import (
    ProviderHealthState,
    ProviderRuntimeIngestError,
    ProviderRuntimeObserver,
    build_negative_provider_probe_observation,
    ingest_negative_provider_probe,
)


SHA = "ce62727b1d8f261112b17b7bb0290f6573119b41"


def probe(
    provider_id="openai",
    condition="INSUFFICIENT_QUOTA",
    **overrides,
):
    payload = {
        "schema": "stock_razor_provider_negative_probe_v1",
        "provider_id": provider_id,
        "condition": condition,
        "observed_at_utc": "2026-10-08T00:10:05+00:00",
        "runtime_instance_id": "provider-probe-1",
        "repo_sha": SHA,
        "probe_source": "secure_e2e_probe",
        "http_status": 429,
        "error_code": "insufficient_quota",
        "error_type": "ApiError",
        "research_only": True,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }
    payload.update(overrides)
    return payload


def test_openai_insufficient_quota_maps_to_exhausted_without_inventing_balance():
    observation = build_negative_provider_probe_observation(probe())
    assert observation.provider_id == "openai"
    assert observation.fields["health_state"].value is ProviderHealthState.EXHAUSTED
    assert observation.fields["billing_status"].value == "INSUFFICIENT_QUOTA"
    assert observation.fields["failure_reason"].value == (
        "INSUFFICIENT_QUOTA|CODE=insufficient_quota|TYPE=ApiError|HTTP=429"
    )
    assert "last_success" not in observation.fields
    assert "quota_total" not in observation.fields
    assert "quota_remaining" not in observation.fields
    assert "latency_ms" not in observation.fields
    assert "freshness_ms" not in observation.fields


def test_credit_balance_exhausted_preserves_specific_billing_status():
    observation = build_negative_provider_probe_observation(
        probe(
            condition="CREDIT_BALANCE_EXHAUSTED",
            error_code="credit_balance_exhausted",
        )
    )
    assert observation.fields["health_state"].value is ProviderHealthState.EXHAUSTED
    assert observation.fields["billing_status"].value == (
        "CREDIT_BALANCE_EXHAUSTED"
    )


def test_anthropic_expired_or_invalid_maps_credential_fail_closed():
    observation = build_negative_provider_probe_observation(
        probe(
            provider_id="anthropic",
            condition="EXPIRED_OR_INVALID",
            http_status=401,
            error_code="authentication_error",
        )
    )
    assert observation.fields["health_state"].value is ProviderHealthState.EXPIRED
    assert observation.fields["credential_status"].value == "EXPIRED_OR_INVALID"
    assert "billing_status" not in observation.fields


def test_auth_failed_maps_failed_without_claiming_expiry():
    observation = build_negative_provider_probe_observation(
        probe(
            provider_id="twelve_data",
            condition="AUTH_FAILED",
            http_status=401,
            error_code="invalid_api_key",
        )
    )
    assert observation.fields["health_state"].value is ProviderHealthState.FAILED
    assert observation.fields["credential_status"].value == "AUTH_FAILED"


def test_rate_limit_maps_rate_limited_only():
    observation = build_negative_provider_probe_observation(
        probe(
            provider_id="tavily",
            condition="RATE_LIMITED",
            http_status=429,
            error_code="rate_limit",
        )
    )
    assert observation.fields["health_state"].value is ProviderHealthState.RATE_LIMITED
    assert "credential_status" not in observation.fields
    assert "billing_status" not in observation.fields


def test_generic_provider_failed_is_scoped_failure_evidence():
    observation = build_negative_provider_probe_observation(
        probe(
            provider_id="eodhd",
            condition="PROVIDER_FAILED",
            http_status=503,
            error_code="upstream_unavailable",
        )
    )
    assert observation.fields["health_state"].value is ProviderHealthState.FAILED
    assert observation.fields["last_failure"].value == datetime(
        2026, 10, 8, 0, 10, 5, tzinfo=timezone.utc
    )


def test_aws_negative_probe_is_infra_failure_not_market_data_admission():
    observation = build_negative_provider_probe_observation(
        probe(
            provider_id="aws",
            condition="PROVIDER_FAILED",
            http_status=503,
            error_code="ssm_unavailable",
        )
    )
    caps = observation.fields["capabilities"].value
    assert caps["negative_evidence_only"] is True
    assert caps["data_admission"] == "NOT_EVALUATED"
    assert caps["radar_admission"] == "BLOCKED"
    assert caps["live_trade"] is False


@pytest.mark.parametrize(
    "provider_id",
    [
        "moomoo_opend",
        "eastmoney",
        "tencent",
        "alpaca",
    ],
)
def test_dedicated_market_data_providers_reject_generic_negative_probe(provider_id):
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="not eligible for generic negative probe ingest",
    ):
        build_negative_provider_probe_observation(
            probe(provider_id=provider_id)
        )


@pytest.mark.parametrize(
    "condition",
    [
        "HEALTHY",
        "PASS",
        "SUCCESS",
        "VALID",
    ],
)
def test_positive_conditions_are_not_supported(condition):
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="unsupported negative provider condition",
    ):
        build_negative_provider_probe_observation(
            probe(condition=condition)
        )


def test_unknown_probe_fields_are_rejected_instead_of_ignored():
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="unsupported field",
    ):
        build_negative_provider_probe_observation(
            probe(body="raw response renamed")
        )


def test_non_string_probe_field_names_are_rejected():
    payload = probe()
    payload[123] = "unexpected"
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="field names must be strings",
    ):
        build_negative_provider_probe_observation(payload)


@pytest.mark.parametrize(
    "field_name",
    [
        "api_key",
        "authorization",
        "Authorization",
        "headers",
        "request_headers",
        "response_body",
        "raw_response",
        "error_message",
        "message",
        "detail",
    ],
)
def test_raw_or_sensitive_probe_fields_are_rejected(field_name):
    with pytest.raises(
        ProviderRuntimeIngestError,
        match="forbidden raw/sensitive field",
    ):
        build_negative_provider_probe_observation(
            probe(**{field_name: "must-not-persist"})
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"research_only": False},
        {"radar_admission": "PASS"},
        {"live_trade": True},
        {"repo_sha": "abc"},
        {"provider_id": "OpenAI"},
        {"schema": "other"},
    ],
)
def test_negative_probe_governance_and_identity_are_fail_closed(overrides):
    with pytest.raises(ProviderRuntimeIngestError):
        build_negative_provider_probe_observation(
            probe(**overrides)
        )


@pytest.mark.parametrize(
    "http_status",
    [
        "429",
        True,
        99,
        600,
    ],
)
def test_http_status_must_be_real_http_integer(http_status):
    with pytest.raises(ProviderRuntimeIngestError, match="http_status"):
        build_negative_provider_probe_observation(
            probe(http_status=http_status)
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("probe_source", "Secure Probe"),
        ("probe_source", "UPPERCASE"),
        ("runtime_instance_id", "runtime id with spaces"),
        ("error_code", "raw error message with spaces"),
        ("error_type", "Bearer secret leaked"),
        ("error_code", "x" * 81),
    ],
)
def test_probe_metadata_must_be_sanitized_tokens(field_name, value):
    with pytest.raises(ProviderRuntimeIngestError):
        build_negative_provider_probe_observation(
            probe(**{field_name: value})
        )


def test_http_status_may_be_absent_when_probe_has_no_http_layer():
    observation = build_negative_provider_probe_observation(
        probe(
            provider_id="aws",
            condition="PROVIDER_FAILED",
            http_status=None,
            error_code="ssm_channel_failed",
        )
    )
    assert observation.fields["capabilities"].value["http_status"] is None


def test_provenance_is_exact_and_contains_no_raw_message():
    observation = build_negative_provider_probe_observation(
        probe(
            provider_id="anthropic",
            condition="EXPIRED_OR_INVALID",
            http_status=401,
            error_code="authentication_error",
            error_type="HttpError",
        )
    )
    evidence = observation.fields["health_state"].provenance
    assert evidence.observed_at == datetime(
        2026, 10, 8, 0, 10, 5, tzinfo=timezone.utc
    )
    assert evidence.source == "provider_negative_probe:secure_e2e_probe"
    assert evidence.runtime_id == "provider-probe-1"
    assert evidence.repo_sha == SHA
    assert evidence.error_code == "EXPIRED_OR_INVALID"
    assert evidence.evidence_id.endswith(":health_state")


def test_capabilities_are_read_only():
    observation = build_negative_provider_probe_observation(probe())
    capabilities = observation.fields["capabilities"].value
    with pytest.raises(TypeError):
        capabilities["radar_admission"] = "PASS"


def test_end_to_end_ingest_uses_static_registry_role_without_positive_promotion():
    snapshot = ingest_negative_provider_probe(
        ProviderRuntimeObserver(),
        probe(
            provider_id="openai",
            condition="INSUFFICIENT_QUOTA",
        ),
    )
    assert snapshot.record.provider_id == "openai"
    assert snapshot.record.role.value == "AI"
    assert snapshot.record.health_state is ProviderHealthState.EXHAUSTED
    assert snapshot.record.billing_status == "INSUFFICIENT_QUOTA"
    assert snapshot.record.last_success is None
    assert snapshot.record.quota_remaining is None


def test_newer_negative_evidence_can_escalate_same_provider_field_state():
    observer = ProviderRuntimeObserver()
    ingest_negative_provider_probe(
        observer,
        probe(
            provider_id="tavily",
            condition="RATE_LIMITED",
            observed_at_utc="2026-10-08T00:10:05+00:00",
        ),
    )
    snapshot = ingest_negative_provider_probe(
        observer,
        probe(
            provider_id="tavily",
            condition="PROVIDER_FAILED",
            observed_at_utc="2026-10-08T00:10:06+00:00",
            http_status=503,
            error_code="upstream_failed",
        ),
    )
    assert snapshot.record.health_state is ProviderHealthState.FAILED
    assert snapshot.record.last_failure == datetime(
        2026, 10, 8, 0, 10, 6, tzinfo=timezone.utc
    )
