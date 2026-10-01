"""Governed preflight contracts for the Radar Rule Validation Harness V0.1.

This module is deliberately a research-only leaf.  It does not backtest a
rule, generate folds, mutate production configuration, or claim a Never-Seen
Holdout.  It freezes the inputs that must be committed *before* an experiment
may ask the existing OOS Consumption Ledger for a holdout claim.

The split is intentional:

1. :func:`evaluate_rule_validation_preflight` validates immutable contract
   binding, point-in-time availability, and the declared experiment budget.
2. Only a passing report is eligible to call the existing
   ``OOSConsumptionLedgerRepository.claim_if_pristine`` path.
3. A later orchestration slice will persist budget reservations and join the
   two steps.  Until then, ``budget_usage`` is explicitly a caller-supplied
   snapshot and must not be represented as an atomic reservation.

Unknown PIT evidence and missing manifest bindings fail closed.  A profitable
result can never compensate for a failed or unknown preflight gate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .experiment_governance import ExperimentManifest
from .temporal_contract import (
    TemporalEvidence,
    TemporalInterval,
    canonical_utc_datetime,
    canonical_utc_text,
    is_available_by,
)

_RULE_CONTRACT_SCHEMA = "radar-rule-contract-v0.1"
_DATASET_SPLIT_SCHEMA = "radar-dataset-split-v0.1"
_EXPERIMENT_BUDGET_SCHEMA = "radar-experiment-budget-v0.1"
_COUNTERFACTUAL_PLAN_SCHEMA = "radar-counterfactual-plan-v0.1"
_PIT_POLICY_SCHEMA = "radar-pit-policy-v0.1"
_HARNESS_CONTRACT_SCHEMA = "radar-rule-validation-harness-v0.1"

REQUIRED_FORBIDDEN_USES = frozenset({"live_order_execution", "production_promotion"})


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class CounterfactualKind(str, Enum):
    WITH_RULE = "with_rule"
    WITHOUT_RULE = "without_rule"
    SHUFFLED_PLACEBO = "shuffled_placebo"
    DELAYED_RULE = "delayed_rule"
    REGIME_CONDITIONED = "regime_conditioned"


REQUIRED_COUNTERFACTUAL_KINDS = frozenset(CounterfactualKind)


def _require_nonempty_str(label: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string, got {value!r}")
    return value.strip()


def _require_non_negative_int(label: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative int, got {value!r}")
    return value


def _canonical_strings(label: str, values: Sequence[str], *, required: bool = True) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{label} must be a sequence of strings, got {values!r}")
    normalized = tuple(sorted({_require_nonempty_str(label, value) for value in values}))
    if required and not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _freeze_evidence(value: Any) -> Any:
    """Recursively freeze diagnostic evidence exposed by a gate result."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_evidence(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_evidence(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(_freeze_evidence(item) for item in value))
    return value


@dataclass(frozen=True)
class RuleContract:
    rule_id: str
    rule_version: str
    hypothesis: str
    input_fields: tuple[str, ...]
    applicable_regimes: tuple[str, ...]
    trigger_contract: str
    expected_effect: str
    invalidation_contract: str
    forbidden_uses: tuple[str, ...] = ("live_order_execution", "production_promotion")

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _require_nonempty_str("rule_id", self.rule_id))
        object.__setattr__(self, "rule_version", _require_nonempty_str("rule_version", self.rule_version))
        object.__setattr__(self, "hypothesis", _require_nonempty_str("hypothesis", self.hypothesis))
        object.__setattr__(self, "input_fields", _canonical_strings("input_fields", self.input_fields))
        object.__setattr__(
            self,
            "applicable_regimes",
            _canonical_strings("applicable_regimes", self.applicable_regimes),
        )
        object.__setattr__(self, "trigger_contract", _require_nonempty_str("trigger_contract", self.trigger_contract))
        object.__setattr__(self, "expected_effect", _require_nonempty_str("expected_effect", self.expected_effect))
        object.__setattr__(
            self,
            "invalidation_contract",
            _require_nonempty_str("invalidation_contract", self.invalidation_contract),
        )
        forbidden = _canonical_strings("forbidden_uses", self.forbidden_uses)
        missing = REQUIRED_FORBIDDEN_USES.difference(forbidden)
        if missing:
            raise ValueError(f"forbidden_uses must include {sorted(missing)!r}")
        object.__setattr__(self, "forbidden_uses", forbidden)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": _RULE_CONTRACT_SCHEMA,
                "rule_id": self.rule_id,
                "rule_version": self.rule_version,
                "hypothesis": self.hypothesis,
                "input_fields": list(self.input_fields),
                "applicable_regimes": list(self.applicable_regimes),
                "trigger_contract": self.trigger_contract,
                "expected_effect": self.expected_effect,
                "invalidation_contract": self.invalidation_contract,
                "forbidden_uses": list(self.forbidden_uses),
            }
        )


@dataclass(frozen=True)
class DatasetSplitContract:
    dataset_id: str
    dataset_version: str
    development: TemporalInterval
    validation: TemporalInterval
    never_seen_holdout: TemporalInterval
    embargo_bars: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_id", _require_nonempty_str("dataset_id", self.dataset_id))
        object.__setattr__(self, "dataset_version", _require_nonempty_str("dataset_version", self.dataset_version))
        for label in ("development", "validation", "never_seen_holdout"):
            if not isinstance(getattr(self, label), TemporalInterval):
                raise ValueError(f"{label} must be a TemporalInterval")
        object.__setattr__(self, "embargo_bars", _require_non_negative_int("embargo_bars", self.embargo_bars))
        if self.development.end > self.validation.start:
            raise ValueError("development and validation intervals must not overlap")
        if self.validation.end > self.never_seen_holdout.start:
            raise ValueError("validation and Never-Seen Holdout intervals must not overlap")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": _DATASET_SPLIT_SCHEMA,
                "dataset_id": self.dataset_id,
                "dataset_version": self.dataset_version,
                "development": {
                    "start": canonical_utc_text(self.development.start),
                    "end": canonical_utc_text(self.development.end),
                },
                "validation": {
                    "start": canonical_utc_text(self.validation.start),
                    "end": canonical_utc_text(self.validation.end),
                },
                "never_seen_holdout": {
                    "start": canonical_utc_text(self.never_seen_holdout.start),
                    "end": canonical_utc_text(self.never_seen_holdout.end),
                },
                "embargo_bars": self.embargo_bars,
            }
        )


@dataclass(frozen=True)
class ExperimentBudget:
    rule_family_id: str
    max_trials: int
    max_parameter_sets: int
    max_model_calls: int
    max_human_mutations: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_family_id", _require_nonempty_str("rule_family_id", self.rule_family_id))
        for field_name in ("max_trials", "max_parameter_sets", "max_model_calls", "max_human_mutations"):
            object.__setattr__(self, field_name, _require_non_negative_int(field_name, getattr(self, field_name)))
        if self.max_trials == 0:
            raise ValueError("max_trials must be positive")
        if self.max_parameter_sets == 0:
            raise ValueError("max_parameter_sets must be positive")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": _EXPERIMENT_BUDGET_SCHEMA,
                "rule_family_id": self.rule_family_id,
                "max_trials": self.max_trials,
                "max_parameter_sets": self.max_parameter_sets,
                "max_model_calls": self.max_model_calls,
                "max_human_mutations": self.max_human_mutations,
            }
        )


@dataclass(frozen=True)
class ExperimentBudgetUsage:
    trials: int = 0
    parameter_sets: int = 0
    model_calls: int = 0
    human_mutations: int = 0

    def __post_init__(self) -> None:
        for field_name in ("trials", "parameter_sets", "model_calls", "human_mutations"):
            object.__setattr__(self, field_name, _require_non_negative_int(field_name, getattr(self, field_name)))

    def plus(self, reservation: "ExperimentBudgetUsage") -> "ExperimentBudgetUsage":
        if not isinstance(reservation, ExperimentBudgetUsage):
            raise ValueError("reservation must be ExperimentBudgetUsage")
        return ExperimentBudgetUsage(
            trials=self.trials + reservation.trials,
            parameter_sets=self.parameter_sets + reservation.parameter_sets,
            model_calls=self.model_calls + reservation.model_calls,
            human_mutations=self.human_mutations + reservation.human_mutations,
        )


@dataclass(frozen=True)
class CounterfactualSpec:
    variant_id: str
    kind: CounterfactualKind
    deterministic_seed: int | None = None
    delay_bars: int | None = None
    regime_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "variant_id", _require_nonempty_str("variant_id", self.variant_id))
        if not isinstance(self.kind, CounterfactualKind):
            raise ValueError(f"kind must be CounterfactualKind, got {self.kind!r}")
        if self.kind is CounterfactualKind.SHUFFLED_PLACEBO:
            if self.deterministic_seed is None:
                raise ValueError("shuffled_placebo requires deterministic_seed")
            _require_non_negative_int("deterministic_seed", self.deterministic_seed)
        elif self.deterministic_seed is not None:
            raise ValueError("deterministic_seed is only valid for shuffled_placebo")
        if self.kind is CounterfactualKind.DELAYED_RULE:
            if self.delay_bars is None or _require_non_negative_int("delay_bars", self.delay_bars) == 0:
                raise ValueError("delayed_rule requires positive delay_bars")
        elif self.delay_bars is not None:
            raise ValueError("delay_bars is only valid for delayed_rule")
        if self.kind is CounterfactualKind.REGIME_CONDITIONED:
            if self.regime_id is None:
                raise ValueError("regime_conditioned requires regime_id")
            object.__setattr__(self, "regime_id", _require_nonempty_str("regime_id", self.regime_id))
        elif self.regime_id is not None:
            raise ValueError("regime_id is only valid for regime_conditioned")

    def payload(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "kind": self.kind.value,
            "deterministic_seed": self.deterministic_seed,
            "delay_bars": self.delay_bars,
            "regime_id": self.regime_id,
        }


@dataclass(frozen=True)
class CounterfactualPlan:
    variants: tuple[CounterfactualSpec, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.variants, tuple) or not all(
            isinstance(variant, CounterfactualSpec) for variant in self.variants
        ):
            raise ValueError("variants must be a tuple of CounterfactualSpec")
        ids = [variant.variant_id for variant in self.variants]
        if len(ids) != len(set(ids)):
            raise ValueError("counterfactual variant_id values must be unique")
        kinds = {variant.kind for variant in self.variants}
        missing = REQUIRED_COUNTERFACTUAL_KINDS.difference(kinds)
        if missing:
            raise ValueError(
                f"counterfactual plan is missing required kinds: {sorted(kind.value for kind in missing)!r}"
            )
        for singleton_kind in (CounterfactualKind.WITH_RULE, CounterfactualKind.WITHOUT_RULE):
            if sum(variant.kind is singleton_kind for variant in self.variants) != 1:
                raise ValueError(f"counterfactual plan requires exactly one {singleton_kind.value}")
        object.__setattr__(
            self,
            "variants",
            tuple(sorted(self.variants, key=lambda variant: (variant.kind.value, variant.variant_id))),
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": _COUNTERFACTUAL_PLAN_SCHEMA,
                "variants": [variant.payload() for variant in self.variants],
            }
        )


@dataclass(frozen=True)
class RuleValidationContract:
    rule: RuleContract
    dataset_split: DatasetSplitContract
    budget: ExperimentBudget
    counterfactual_plan: CounterfactualPlan
    schema_version: str = _HARNESS_CONTRACT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.rule, RuleContract):
            raise ValueError("rule must be RuleContract")
        if not isinstance(self.dataset_split, DatasetSplitContract):
            raise ValueError("dataset_split must be DatasetSplitContract")
        if not isinstance(self.budget, ExperimentBudget):
            raise ValueError("budget must be ExperimentBudget")
        if not isinstance(self.counterfactual_plan, CounterfactualPlan):
            raise ValueError("counterfactual_plan must be CounterfactualPlan")
        object.__setattr__(self, "schema_version", _require_nonempty_str("schema_version", self.schema_version))

    @property
    def _component_fingerprints(self) -> Mapping[str, str]:
        pit_policy = _fingerprint(
            {
                "schema": _PIT_POLICY_SCHEMA,
                "availability_rule": "available_at_lte_decision_time",
                "unknown_result": "block",
                "input_fields": list(self.rule.input_fields),
            }
        )
        return MappingProxyType(
            {
                "rule_contract": self.rule.fingerprint,
                "dataset_split": self.dataset_split.fingerprint,
                "experiment_budget": self.budget.fingerprint,
                "counterfactual_plan": self.counterfactual_plan.fingerprint,
                "pit_policy": pit_policy,
            }
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": self.schema_version,
                "governed_components": dict(sorted(self._component_fingerprints.items())),
            }
        )

    @property
    def governed_components(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                **self._component_fingerprints,
                "rule_validation_contract": self.fingerprint,
            }
        )


@dataclass(frozen=True)
class PITInputEvidence:
    evidence_id: str
    field_name: str
    temporal_evidence: TemporalEvidence | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _require_nonempty_str("evidence_id", self.evidence_id))
        object.__setattr__(self, "field_name", _require_nonempty_str("field_name", self.field_name))
        if self.temporal_evidence is not None and not isinstance(self.temporal_evidence, TemporalEvidence):
            raise ValueError("temporal_evidence must be TemporalEvidence or None")


@dataclass(frozen=True)
class HarnessGateResult:
    gate: str
    status: GateStatus
    reason: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate", _require_nonempty_str("gate", self.gate))
        if not isinstance(self.status, GateStatus):
            raise ValueError("status must be GateStatus")
        object.__setattr__(self, "reason", _require_nonempty_str("reason", self.reason))
        if not isinstance(self.evidence, Mapping):
            raise ValueError("evidence must be a mapping")
        object.__setattr__(self, "evidence", _freeze_evidence(self.evidence))


@dataclass(frozen=True)
class RuleValidationPreflightReport:
    experiment_id: str
    contract_fingerprint: str
    decision_time: datetime
    gate_results: tuple[HarnessGateResult, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "experiment_id", _require_nonempty_str("experiment_id", self.experiment_id))
        object.__setattr__(
            self, "contract_fingerprint", _require_nonempty_str("contract_fingerprint", self.contract_fingerprint)
        )
        object.__setattr__(self, "decision_time", canonical_utc_datetime(self.decision_time))
        if not isinstance(self.gate_results, tuple) or not self.gate_results:
            raise ValueError("gate_results must be a non-empty tuple")
        if not all(isinstance(result, HarnessGateResult) for result in self.gate_results):
            raise ValueError("gate_results must contain only HarnessGateResult")

    @property
    def eligible_for_holdout_claim(self) -> bool:
        return all(result.status is GateStatus.PASS for result in self.gate_results)


def evaluate_rule_validation_preflight(
    *,
    contract: RuleValidationContract,
    manifest: ExperimentManifest,
    decision_time: datetime,
    pit_evidence: Sequence[PITInputEvidence],
    budget_usage: ExperimentBudgetUsage,
    budget_reservation: ExperimentBudgetUsage,
) -> RuleValidationPreflightReport:
    """Evaluate fail-closed gates before any Never-Seen Holdout claim.

    ``budget_usage`` is a snapshot, not a persistent or atomic reservation.
    The result therefore proves contract-level budget fit only.  The future
    persistent registry must re-check and reserve budget in its write
    transaction before this report can be treated as execution authority.
    """

    if not isinstance(contract, RuleValidationContract):
        raise ValueError("contract must be RuleValidationContract")
    if not isinstance(manifest, ExperimentManifest):
        raise ValueError("manifest must be ExperimentManifest")
    decision_time = canonical_utc_datetime(decision_time)
    if not isinstance(budget_usage, ExperimentBudgetUsage):
        raise ValueError("budget_usage must be ExperimentBudgetUsage")
    if not isinstance(budget_reservation, ExperimentBudgetUsage):
        raise ValueError("budget_reservation must be ExperimentBudgetUsage")

    gates = (
        _manifest_binding_gate(contract, manifest),
        _dataset_split_gate(contract.dataset_split),
        _pit_gate(contract.rule, decision_time, pit_evidence),
        _budget_gate(contract.budget, budget_usage, budget_reservation),
        _counterfactual_gate(contract.counterfactual_plan),
    )
    return RuleValidationPreflightReport(
        experiment_id=manifest.experiment_id,
        contract_fingerprint=contract.fingerprint,
        decision_time=decision_time,
        gate_results=gates,
    )


def _manifest_binding_gate(contract: RuleValidationContract, manifest: ExperimentManifest) -> HarnessGateResult:
    expected = contract.governed_components
    missing = tuple(sorted(set(expected).difference(manifest.governed_components)))
    mismatched = tuple(
        sorted(
            key
            for key in expected
            if key in manifest.governed_components and manifest.governed_components[key] != expected[key]
        )
    )
    if mismatched:
        status = GateStatus.FAIL
        reason = "manifest contains governed component fingerprints that conflict with the frozen contract"
    elif missing:
        status = GateStatus.UNKNOWN
        reason = "manifest does not bind every governed rule-validation component"
    else:
        status = GateStatus.PASS
        reason = "manifest is bound to every governed rule-validation component"
    return HarnessGateResult(
        gate="manifest_binding",
        status=status,
        reason=reason,
        evidence={"missing_keys": missing, "mismatched_keys": mismatched},
    )


def _dataset_split_gate(split: DatasetSplitContract) -> HarnessGateResult:
    return HarnessGateResult(
        gate="dataset_split",
        status=GateStatus.PASS,
        reason="development, validation, and Never-Seen Holdout intervals are ordered and non-overlapping",
        evidence={
            "dataset_id": split.dataset_id,
            "dataset_version": split.dataset_version,
            "split_fingerprint": split.fingerprint,
            "holdout_start": canonical_utc_text(split.never_seen_holdout.start),
            "holdout_end": canonical_utc_text(split.never_seen_holdout.end),
        },
    )


def _pit_gate(
    rule: RuleContract,
    decision_time: datetime,
    evidence_items: Sequence[PITInputEvidence],
) -> HarnessGateResult:
    by_field: dict[str, PITInputEvidence] = {}
    evidence_ids: set[str] = set()
    for item in evidence_items:
        if not isinstance(item, PITInputEvidence):
            raise ValueError("pit_evidence must contain only PITInputEvidence")
        if item.field_name not in rule.input_fields:
            raise ValueError(f"PIT evidence references undeclared input field {item.field_name!r}")
        if item.field_name in by_field:
            raise ValueError(f"duplicate PIT evidence for input field {item.field_name!r}")
        if item.evidence_id in evidence_ids:
            raise ValueError(f"duplicate PIT evidence_id {item.evidence_id!r}")
        by_field[item.field_name] = item
        evidence_ids.add(item.evidence_id)

    unknown_fields = tuple(
        field_name
        for field_name in rule.input_fields
        if field_name not in by_field or by_field[field_name].temporal_evidence is None
    )
    late_fields = tuple(
        field_name
        for field_name in rule.input_fields
        if field_name in by_field
        and by_field[field_name].temporal_evidence is not None
        and not is_available_by(by_field[field_name].temporal_evidence, decision_time)
    )
    if late_fields:
        status = GateStatus.FAIL
        reason = "one or more rule inputs were not available by the decision time"
    elif unknown_fields:
        status = GateStatus.UNKNOWN
        reason = "one or more rule inputs have unknown point-in-time availability"
    else:
        status = GateStatus.PASS
        reason = "all declared rule inputs were available by the decision time"
    return HarnessGateResult(
        gate="pit_anti_leak",
        status=status,
        reason=reason,
        evidence={
            "decision_time": canonical_utc_text(decision_time),
            "unknown_fields": unknown_fields,
            "late_fields": late_fields,
            "evidence_ids": tuple(sorted(evidence_ids)),
        },
    )


def _budget_gate(
    budget: ExperimentBudget,
    usage: ExperimentBudgetUsage,
    reservation: ExperimentBudgetUsage,
) -> HarnessGateResult:
    projected = usage.plus(reservation)
    limits = {
        "trials": budget.max_trials,
        "parameter_sets": budget.max_parameter_sets,
        "model_calls": budget.max_model_calls,
        "human_mutations": budget.max_human_mutations,
    }
    projected_values = {
        "trials": projected.trials,
        "parameter_sets": projected.parameter_sets,
        "model_calls": projected.model_calls,
        "human_mutations": projected.human_mutations,
    }
    exceeded = tuple(sorted(name for name, value in projected_values.items() if value > limits[name]))
    return HarnessGateResult(
        gate="experiment_budget",
        status=GateStatus.FAIL if exceeded else GateStatus.PASS,
        reason=(
            "declared reservation exceeds the frozen experiment budget"
            if exceeded
            else "declared reservation fits within the frozen experiment budget snapshot"
        ),
        evidence={
            "budget_fingerprint": budget.fingerprint,
            "snapshot_only": True,
            "projected": projected_values,
            "limits": limits,
            "exceeded_dimensions": exceeded,
        },
    )


def _counterfactual_gate(plan: CounterfactualPlan) -> HarnessGateResult:
    return HarnessGateResult(
        gate="counterfactual_coverage",
        status=GateStatus.PASS,
        reason="the frozen plan contains every required baseline and counterfactual family",
        evidence={
            "plan_fingerprint": plan.fingerprint,
            "variant_ids": tuple(variant.variant_id for variant in plan.variants),
            "kinds": tuple(sorted({variant.kind.value for variant in plan.variants})),
        },
    )
