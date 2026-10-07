"""Fail-closed provider lifecycle, cost guard, and fallback contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Mapping


class ProviderRole(str, Enum):
    PRIMARY = "PRIMARY"
    FALLBACK = "FALLBACK"
    CROSS_CHECK = "CROSS_CHECK"
    AI = "AI"
    SEARCH = "SEARCH"
    INFRA = "INFRA"


class ProviderHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    DEGRADED = "DEGRADED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class GuardSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class DataAdmission(str, Enum):
    PASS = "PASS"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


class CostAction(str, Enum):
    RECHARGE = "RECHARGE"
    UPGRADE_PLAN = "UPGRADE_PLAN"
    ENABLE_PAID_FEATURE = "ENABLE_PAID_FEATURE"
    RAISE_BILLING_LIMIT = "RAISE_BILLING_LIMIT"
    ENABLE_AUTO_RECHARGE = "ENABLE_AUTO_RECHARGE"


def _require_aware(value: datetime | None, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class ProviderLifecycleRecord:
    provider_id: str
    role: ProviderRole
    market_scope: tuple[str, ...]
    credential_status: str = "UNKNOWN"
    credential_expiry: datetime | None = None
    plan: str | None = None
    quota_total: float | None = None
    quota_used: float | None = None
    quota_remaining: float | None = None
    quota_reset_at: datetime | None = None
    rate_limit: str | None = None
    billing_status: str = "UNKNOWN"
    auto_recharge_enabled: bool | None = None
    last_success: datetime | None = None
    last_failure: datetime | None = None
    failure_reason: str | None = None
    latency_ms: float | None = None
    freshness_ms: float | None = None
    coverage: str | None = None
    fallback_provider: str | None = None
    decision_criticality: str = "UNKNOWN"
    health_state: ProviderHealthState = ProviderHealthState.UNKNOWN
    daily_cost: float | None = None
    mtd_cost: float | None = None
    projected_monthly_cost: float | None = None
    cost_anomaly: bool | None = None
    budget_remaining: float | None = None
    free_period_ends_at: datetime | None = None
    usage_per_day: float | None = None
    capabilities: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id is required")
        if not self.market_scope:
            raise ValueError("market_scope must not be empty")
        for field_name in (
            "credential_expiry",
            "quota_reset_at",
            "last_success",
            "last_failure",
            "free_period_ends_at",
        ):
            _require_aware(getattr(self, field_name), field_name)
        for field_name in (
            "quota_total",
            "quota_used",
            "quota_remaining",
            "latency_ms",
            "freshness_ms",
            "daily_cost",
            "mtd_cost",
            "projected_monthly_cost",
            "budget_remaining",
            "usage_per_day",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be >= 0")


@dataclass(frozen=True)
class ProviderAlert:
    severity: GuardSeverity
    code: str
    message: str


@dataclass(frozen=True)
class ProviderGuardAssessment:
    provider_id: str
    effective_health: ProviderHealthState
    alerts: tuple[ProviderAlert, ...]
    projected_exhaustion_at: datetime | None
    auto_spend_permitted: bool
    user_approval_required: bool


@dataclass(frozen=True)
class CostGuardDecision:
    action: CostAction
    permitted: bool
    outcome: str
    reason: str


def evaluate_cost_action(action: CostAction) -> CostGuardDecision:
    return CostGuardDecision(
        action=action,
        permitted=False,
        outcome="USER_APPROVAL_REQUIRED",
        reason="AUTOMATIC_PROVIDER_SPEND_FORBIDDEN",
    )


_STATE_RANK = {
    ProviderHealthState.HEALTHY: 0,
    ProviderHealthState.UNKNOWN: 0,
    ProviderHealthState.WARNING: 1,
    ProviderHealthState.DEGRADED: 2,
    ProviderHealthState.RATE_LIMITED: 3,
    ProviderHealthState.FAILED: 4,
    ProviderHealthState.EXHAUSTED: 5,
    ProviderHealthState.EXPIRED: 6,
}


def _escalate(current: ProviderHealthState, candidate: ProviderHealthState) -> ProviderHealthState:
    if candidate == ProviderHealthState.UNKNOWN:
        return current
    if current == ProviderHealthState.UNKNOWN:
        return candidate
    return candidate if _STATE_RANK[candidate] > _STATE_RANK[current] else current


def _credential_problem_state(value: str) -> ProviderHealthState | None:
    normalized = str(value or "UNKNOWN").strip().upper()
    if normalized in {"EXPIRED", "EXPIRED_OR_INVALID"}:
        return ProviderHealthState.EXPIRED
    if normalized in {"INVALID", "AUTH_FAILED", "AUTHENTICATION_FAILED", "FAILED"}:
        return ProviderHealthState.FAILED
    if normalized in {"WARNING", "EXPIRING"}:
        return ProviderHealthState.WARNING
    return None


def _billing_problem_state(value: str) -> ProviderHealthState | None:
    normalized = str(value or "UNKNOWN").strip().upper()
    if normalized in {
        "EXHAUSTED",
        "CREDIT_EXHAUSTED",
        "CREDIT_BALANCE_EXHAUSTED",
        "INSUFFICIENT_QUOTA",
    }:
        return ProviderHealthState.EXHAUSTED
    if normalized in {"FAILED", "PAST_DUE", "SUSPENDED", "PAYMENT_FAILED"}:
        return ProviderHealthState.FAILED
    if normalized == "WARNING":
        return ProviderHealthState.WARNING
    return None


def assess_provider(record: ProviderLifecycleRecord, *, now: datetime) -> ProviderGuardAssessment:
    _require_aware(now, "now")
    effective = record.health_state
    alerts: list[ProviderAlert] = []

    credential_problem = _credential_problem_state(record.credential_status)
    if credential_problem is not None:
        effective = _escalate(effective, credential_problem)
        alerts.append(ProviderAlert(
            GuardSeverity.CRITICAL if credential_problem in {
                ProviderHealthState.EXPIRED,
                ProviderHealthState.FAILED,
            } else GuardSeverity.WARNING,
            f"CREDENTIAL_STATUS_{credential_problem.value}",
            f"Provider credential status is {credential_problem.value.lower()}.",
        ))

    billing_problem = _billing_problem_state(record.billing_status)
    if billing_problem is not None:
        effective = _escalate(effective, billing_problem)
        alerts.append(ProviderAlert(
            GuardSeverity.CRITICAL if billing_problem in {
                ProviderHealthState.EXHAUSTED,
                ProviderHealthState.FAILED,
            } else GuardSeverity.WARNING,
            f"BILLING_STATUS_{billing_problem.value}",
            f"Provider billing status is {billing_problem.value.lower()}.",
        ))

    expiry = record.credential_expiry
    if expiry is not None:
        seconds = (expiry - now).total_seconds()
        if seconds <= 0:
            effective = _escalate(effective, ProviderHealthState.EXPIRED)
            alerts.append(ProviderAlert(
                GuardSeverity.CRITICAL,
                "CREDENTIAL_EXPIRED",
                "Provider credential is expired.",
            ))
        else:
            days = seconds / 86400
            if days <= 30:
                effective = _escalate(effective, ProviderHealthState.WARNING)
                if days <= 1:
                    severity, band = GuardSeverity.CRITICAL, "1D"
                elif days <= 3:
                    severity, band = GuardSeverity.WARNING, "3D"
                elif days <= 7:
                    severity, band = GuardSeverity.WARNING, "7D"
                elif days <= 14:
                    severity, band = GuardSeverity.INFO, "14D"
                else:
                    severity, band = GuardSeverity.INFO, "30D"
                alerts.append(ProviderAlert(
                    severity,
                    f"CREDENTIAL_EXPIRY_{band}",
                    f"Provider credential expires within {band.lower()}.",
                ))

    if record.quota_total is not None and record.quota_total > 0 and record.quota_remaining is not None:
        ratio = record.quota_remaining / record.quota_total
        if record.quota_remaining <= 0:
            effective = _escalate(effective, ProviderHealthState.EXHAUSTED)
            alerts.append(ProviderAlert(
                GuardSeverity.CRITICAL,
                "QUOTA_EXHAUSTED",
                "Provider quota is exhausted.",
            ))
        elif ratio < 0.05:
            effective = _escalate(effective, ProviderHealthState.WARNING)
            alerts.append(ProviderAlert(
                GuardSeverity.CRITICAL,
                "QUOTA_BELOW_5_PERCENT",
                "Provider quota remaining is below 5%.",
            ))
        elif ratio < 0.15:
            effective = _escalate(effective, ProviderHealthState.WARNING)
            alerts.append(ProviderAlert(
                GuardSeverity.WARNING,
                "QUOTA_BELOW_15_PERCENT",
                "Provider quota remaining is below 15%.",
            ))
        elif ratio < 0.25:
            effective = _escalate(effective, ProviderHealthState.WARNING)
            alerts.append(ProviderAlert(
                GuardSeverity.INFO,
                "QUOTA_BELOW_25_PERCENT",
                "Provider quota remaining is below 25%.",
            ))

    projected_exhaustion_at = None
    if (
        record.quota_remaining is not None
        and record.quota_remaining > 0
        and record.usage_per_day is not None
        and record.usage_per_day > 0
    ):
        projected_exhaustion_at = now + timedelta(
            days=record.quota_remaining / record.usage_per_day
        )

    user_approval_required = False
    if record.auto_recharge_enabled is True:
        effective = _escalate(effective, ProviderHealthState.WARNING)
        user_approval_required = True
        alerts.append(ProviderAlert(
            GuardSeverity.CRITICAL,
            "AUTO_RECHARGE_ENABLED",
            "Auto recharge is enabled externally; STOCK RAZOR must not initiate or raise paid limits.",
        ))

    if record.cost_anomaly is True:
        effective = _escalate(effective, ProviderHealthState.WARNING)
        alerts.append(ProviderAlert(
            GuardSeverity.CRITICAL,
            "COST_ANOMALY",
            "Provider cost anomaly is active.",
        ))

    return ProviderGuardAssessment(
        provider_id=record.provider_id,
        effective_health=effective,
        alerts=tuple(alerts),
        projected_exhaustion_at=projected_exhaustion_at,
        auto_spend_permitted=False,
        user_approval_required=user_approval_required,
    )


@dataclass(frozen=True)
class FallbackQualityChecks:
    freshness_ok: bool | None
    coverage_ok: bool | None
    timestamp_currentness_ok: bool | None
    latency_ok: bool | None
    cross_provider_sanity_ok: bool | None

    def failed_or_unknown(self) -> tuple[str, ...]:
        values = {
            "freshness": self.freshness_ok,
            "coverage": self.coverage_ok,
            "timestamp_currentness": self.timestamp_currentness_ok,
            "latency": self.latency_ok,
            "cross_provider_sanity": self.cross_provider_sanity_ok,
        }
        return tuple(name for name, passed in values.items() if passed is not True)


@dataclass(frozen=True)
class FallbackAssessment:
    admission: DataAdmission
    outcome: str
    fallback_used: bool
    reasons: tuple[str, ...]


def evaluate_fallback(*, fallback_health: ProviderHealthState, checks: FallbackQualityChecks) -> FallbackAssessment:
    blocked_health = {
        ProviderHealthState.UNKNOWN,
        ProviderHealthState.EXHAUSTED,
        ProviderHealthState.EXPIRED,
        ProviderHealthState.RATE_LIMITED,
        ProviderHealthState.FAILED,
    }
    if fallback_health in blocked_health:
        return FallbackAssessment(
            admission=DataAdmission.BLOCKED,
            outcome="BLOCKED",
            fallback_used=True,
            reasons=(f"FALLBACK_HEALTH_{fallback_health.value}",),
        )

    failed = checks.failed_or_unknown()
    if failed:
        return FallbackAssessment(
            admission=DataAdmission.BLOCKED,
            outcome="BLOCKED",
            fallback_used=True,
            reasons=tuple(f"CHECK_{name.upper()}_NOT_PASS" for name in failed),
        )

    if fallback_health in {ProviderHealthState.WARNING, ProviderHealthState.DEGRADED}:
        return FallbackAssessment(
            admission=DataAdmission.DEGRADED,
            outcome="DEGRADED",
            fallback_used=True,
            reasons=(f"FALLBACK_HEALTH_{fallback_health.value}",),
        )

    return FallbackAssessment(
        admission=DataAdmission.PASS,
        outcome="PASS_WITH_FALLBACK",
        fallback_used=True,
        reasons=("FALLBACK_QUALITY_GATE_PASS",),
    )
