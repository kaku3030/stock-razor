"""Persistent registration outcomes for the Rule Validation Harness.

This module owns only immutable, budget-consuming experiment registrations.
It deliberately does not claim, reveal, or burn a Never-Seen Holdout: that
authority remains with :mod:`oos_consumption` and its persistent Ledger.

A successful registration permanently consumes its declared experiment
budget.  There is no release or edit operation, because a release-after-seeing
an unsuccessful run would turn the budget into a retry loophole.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .rule_validation_contract import ExperimentBudgetUsage, RuleValidationPreflightReport
from .temporal_contract import canonical_utc_datetime


def _require_nonempty_str(label: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string, got {value!r}")
    return value.strip()


def compute_registration_operation_fingerprint(
    *,
    experiment_id: str,
    manifest_hash: str,
    contract_fingerprint: str,
    rule_family_id: str,
    budget_fingerprint: str,
    reservation: ExperimentBudgetUsage,
    pit_evidence_fingerprint: str,
    decision_time: datetime,
    declared_at: datetime,
) -> str:
    """Canonical semantic identity for one atomic registration request."""

    if not isinstance(reservation, ExperimentBudgetUsage):
        raise ValueError("reservation must be ExperimentBudgetUsage")
    payload = {
        "experiment_id": _require_nonempty_str("experiment_id", experiment_id),
        "manifest_hash": _require_nonempty_str("manifest_hash", manifest_hash),
        "contract_fingerprint": _require_nonempty_str("contract_fingerprint", contract_fingerprint),
        "rule_family_id": _require_nonempty_str("rule_family_id", rule_family_id),
        "budget_fingerprint": _require_nonempty_str("budget_fingerprint", budget_fingerprint),
        "pit_evidence_fingerprint": _require_nonempty_str(
            "pit_evidence_fingerprint", pit_evidence_fingerprint
        ),
        "reservation": {
            "trials": reservation.trials,
            "parameter_sets": reservation.parameter_sets,
            "model_calls": reservation.model_calls,
            "human_mutations": reservation.human_mutations,
        },
        "decision_time": canonical_utc_datetime(decision_time).isoformat(timespec="microseconds"),
        "declared_at": canonical_utc_datetime(declared_at).isoformat(timespec="microseconds"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ExperimentRegistrationStatus(str, Enum):
    RESERVED = "reserved"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    PREFLIGHT_BLOCKED = "preflight_blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ExperimentRegistryIdempotencyConflictError(ValueError):
    """An operation id was reused for a different semantic registration."""


class ExperimentRegistryIdentityConflictError(ValueError):
    """An experiment id was already registered with another definition."""


class ExperimentRegistryBudgetPolicyConflictError(ValueError):
    """A rule family attempted to silently replace its frozen budget policy."""


@dataclass(frozen=True)
class ExperimentRegistration:
    registration_id: int
    operation_id: str
    experiment_id: str
    manifest_hash: str
    contract_fingerprint: str
    rule_family_id: str
    budget_fingerprint: str
    reservation: ExperimentBudgetUsage
    decision_time: datetime
    declared_at: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        if isinstance(self.registration_id, bool) or not isinstance(self.registration_id, int) or self.registration_id <= 0:
            raise ValueError("registration_id must be a positive int")
        for name in (
            "operation_id",
            "experiment_id",
            "manifest_hash",
            "contract_fingerprint",
            "rule_family_id",
            "budget_fingerprint",
        ):
            object.__setattr__(self, name, _require_nonempty_str(name, getattr(self, name)))
        if not isinstance(self.reservation, ExperimentBudgetUsage):
            raise ValueError("reservation must be ExperimentBudgetUsage")
        for name in ("decision_time", "declared_at", "recorded_at"):
            object.__setattr__(self, name, canonical_utc_datetime(getattr(self, name)))


@dataclass(frozen=True)
class ExperimentRegistrationResult:
    operation_id: str
    status: ExperimentRegistrationStatus
    preflight_report: RuleValidationPreflightReport
    usage_before: ExperimentBudgetUsage
    usage_after: ExperimentBudgetUsage
    registration: ExperimentRegistration | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _require_nonempty_str("operation_id", self.operation_id))
        if not isinstance(self.status, ExperimentRegistrationStatus):
            raise ValueError("status must be ExperimentRegistrationStatus")
        if not isinstance(self.preflight_report, RuleValidationPreflightReport):
            raise ValueError("preflight_report must be RuleValidationPreflightReport")
        if not isinstance(self.usage_before, ExperimentBudgetUsage):
            raise ValueError("usage_before must be ExperimentBudgetUsage")
        if not isinstance(self.usage_after, ExperimentBudgetUsage):
            raise ValueError("usage_after must be ExperimentBudgetUsage")
        if self.registration is not None and not isinstance(self.registration, ExperimentRegistration):
            raise ValueError("registration must be ExperimentRegistration or None")
