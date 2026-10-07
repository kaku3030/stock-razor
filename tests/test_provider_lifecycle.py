from datetime import datetime, timedelta, timezone

import pytest

from src.services.provider_lifecycle import (
    DEFAULT_PROVIDER_REGISTRY,
    CostAction,
    DataAdmission,
    FallbackQualityChecks,
    ProviderHealthState,
    ProviderLifecycleRecord,
    ProviderRole,
    assess_provider,
    evaluate_cost_action,
    evaluate_fallback,
)


NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def record(**kwargs):
    values = {
        "provider_id": "example",
        "role": ProviderRole.FALLBACK,
        "market_scope": ("US",),
    }
    values.update(kwargs)
    return ProviderLifecycleRecord(**values)


def all_checks(value=True):
    return FallbackQualityChecks(
        freshness_ok=value,
        coverage_ok=value,
        timestamp_currentness_ok=value,
        latency_ok=value,
        cross_provider_sanity_ok=value,
    )


def test_unknown_is_not_silently_promoted_to_healthy():
    result = assess_provider(record(), now=NOW)
    assert result.effective_health is ProviderHealthState.UNKNOWN
    assert result.auto_spend_permitted is False


@pytest.mark.parametrize("status", ["EXPIRED", "EXPIRED_OR_INVALID"])
def test_observed_anthropic_expiry_aliases_are_fail_closed(status):
    result = assess_provider(
        record(credential_status=status),
        now=NOW,
    )
    assert result.effective_health is ProviderHealthState.EXPIRED


@pytest.mark.parametrize("status", ["CREDIT_BALANCE_EXHAUSTED", "INSUFFICIENT_QUOTA"])
def test_observed_openai_quota_aliases_are_exhausted(status):
    result = assess_provider(
        record(billing_status=status),
        now=NOW,
    )
    assert result.effective_health is ProviderHealthState.EXHAUSTED


def test_explicit_credential_expired_state_is_fail_closed():
    result = assess_provider(
        record(credential_status="EXPIRED"),
        now=NOW,
    )
    assert result.effective_health is ProviderHealthState.EXPIRED
    assert "CREDENTIAL_STATUS_EXPIRED" in {alert.code for alert in result.alerts}


def test_credit_balance_exhausted_is_provider_exhausted():
    result = assess_provider(
        record(billing_status="CREDIT_BALANCE_EXHAUSTED"),
        now=NOW,
    )
    assert result.effective_health is ProviderHealthState.EXHAUSTED
    assert "BILLING_STATUS_EXHAUSTED" in {alert.code for alert in result.alerts}


def test_valid_credential_alone_does_not_promote_unknown_provider_health():
    result = assess_provider(
        record(credential_status="VALID"),
        now=NOW,
    )
    assert result.effective_health is ProviderHealthState.UNKNOWN


def test_specific_expiry_or_exhaustion_is_not_masked_by_generic_failure():
    expired = assess_provider(
        record(
            health_state=ProviderHealthState.FAILED,
            credential_status="EXPIRED",
        ),
        now=NOW,
    )
    exhausted = assess_provider(
        record(
            health_state=ProviderHealthState.FAILED,
            billing_status="CREDIT_BALANCE_EXHAUSTED",
        ),
        now=NOW,
    )
    assert expired.effective_health is ProviderHealthState.EXPIRED
    assert exhausted.effective_health is ProviderHealthState.EXHAUSTED


def test_expired_credential_is_fail_closed():
    result = assess_provider(
        record(
            health_state=ProviderHealthState.HEALTHY,
            credential_expiry=NOW - timedelta(seconds=1),
        ),
        now=NOW,
    )
    assert result.effective_health is ProviderHealthState.EXPIRED
    assert "CREDENTIAL_EXPIRED" in {alert.code for alert in result.alerts}


@pytest.mark.parametrize(
    ("days", "code"),
    [
        (29, "CREDENTIAL_EXPIRY_30D"),
        (13, "CREDENTIAL_EXPIRY_14D"),
        (6, "CREDENTIAL_EXPIRY_7D"),
        (2, "CREDENTIAL_EXPIRY_3D"),
        (0.5, "CREDENTIAL_EXPIRY_1D"),
    ],
)
def test_credential_warning_bands(days, code):
    result = assess_provider(
        record(
            health_state=ProviderHealthState.HEALTHY,
            credential_expiry=NOW + timedelta(days=days),
        ),
        now=NOW,
    )
    assert result.effective_health is ProviderHealthState.WARNING
    assert code in {alert.code for alert in result.alerts}


def test_quota_zero_is_exhausted():
    result = assess_provider(
        record(
            health_state=ProviderHealthState.HEALTHY,
            quota_total=100,
            quota_used=100,
            quota_remaining=0,
        ),
        now=NOW,
    )
    assert result.effective_health is ProviderHealthState.EXHAUSTED


@pytest.mark.parametrize(
    ("remaining", "code"),
    [
        (24, "QUOTA_BELOW_25_PERCENT"),
        (14, "QUOTA_BELOW_15_PERCENT"),
        (4, "QUOTA_BELOW_5_PERCENT"),
    ],
)
def test_quota_warning_thresholds(remaining, code):
    result = assess_provider(
        record(
            health_state=ProviderHealthState.HEALTHY,
            quota_total=100,
            quota_remaining=remaining,
        ),
        now=NOW,
    )
    assert result.effective_health is ProviderHealthState.WARNING
    assert code in {alert.code for alert in result.alerts}


def test_projected_exhaustion_uses_observed_burn_rate():
    result = assess_provider(
        record(quota_remaining=42, usage_per_day=10),
        now=NOW,
    )
    assert result.projected_exhaustion_at == NOW + timedelta(days=4.2)


@pytest.mark.parametrize("action", list(CostAction))
def test_all_provider_spend_actions_require_explicit_user_approval(action):
    decision = evaluate_cost_action(action)
    assert decision.permitted is False
    assert decision.outcome == "USER_APPROVAL_REQUIRED"
    assert decision.reason == "AUTOMATIC_PROVIDER_SPEND_FORBIDDEN"


def test_auto_recharge_is_never_authorized_by_radar():
    result = assess_provider(
        record(
            health_state=ProviderHealthState.HEALTHY,
            auto_recharge_enabled=True,
        ),
        now=NOW,
    )
    assert result.auto_spend_permitted is False
    assert result.user_approval_required is True
    assert "AUTO_RECHARGE_ENABLED" in {alert.code for alert in result.alerts}


def test_fallback_unknown_quality_blocks():
    checks = FallbackQualityChecks(
        freshness_ok=True,
        coverage_ok=True,
        timestamp_currentness_ok=None,
        latency_ok=True,
        cross_provider_sanity_ok=True,
    )
    result = evaluate_fallback(
        fallback_health=ProviderHealthState.HEALTHY,
        checks=checks,
    )
    assert result.admission is DataAdmission.BLOCKED
    assert result.outcome == "BLOCKED"


def test_fallback_healthy_and_full_quality_can_pass_with_fallback():
    result = evaluate_fallback(
        fallback_health=ProviderHealthState.HEALTHY,
        checks=all_checks(),
    )
    assert result.admission is DataAdmission.PASS
    assert result.outcome == "PASS_WITH_FALLBACK"


def test_fallback_degraded_never_displays_normal():
    result = evaluate_fallback(
        fallback_health=ProviderHealthState.DEGRADED,
        checks=all_checks(),
    )
    assert result.admission is DataAdmission.DEGRADED
    assert result.outcome == "DEGRADED"


@pytest.mark.parametrize(
    "state",
    [
        ProviderHealthState.UNKNOWN,
        ProviderHealthState.EXHAUSTED,
        ProviderHealthState.EXPIRED,
        ProviderHealthState.RATE_LIMITED,
        ProviderHealthState.FAILED,
    ],
)
def test_unqualified_fallback_states_block(state):
    result = evaluate_fallback(
        fallback_health=state,
        checks=all_checks(),
    )
    assert result.admission is DataAdmission.BLOCKED


def test_registry_provider_ids_match_runtime_lineage_names():
    assert DEFAULT_PROVIDER_REGISTRY["eastmoney"].fallback_provider == "tencent"
    assert DEFAULT_PROVIDER_REGISTRY["tencent"].provider_id == "tencent"


def test_registry_contains_required_providers_and_true_capability_notes():
    required = {
        "moomoo_opend",
        "eastmoney",
        "alpaca",
        "twelve_data",
        "eodhd",
        "openai",
        "anthropic",
        "tavily",
        "aws",
    }
    assert required.issubset(DEFAULT_PROVIDER_REGISTRY)
    eodhd = DEFAULT_PROVIDER_REGISTRY["eodhd"]
    assert any("do not provide 1m" in note for note in eodhd.capability_notes)
    alpaca = DEFAULT_PROVIDER_REGISTRY["alpaca"]
    assert any("SIP entitlement must never be assumed" in note for note in alpaca.capability_notes)


def test_naive_lifecycle_timestamps_are_rejected():
    with pytest.raises(ValueError, match="credential_expiry must be timezone-aware"):
        record(credential_expiry=datetime(2026, 10, 8))
