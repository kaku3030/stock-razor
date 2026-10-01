"""Permanent contract tests for Radar Rule Validation Harness preflight."""

import ast
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.services.strategy_lab.experiment_governance import ExperimentManifest
from src.services.strategy_lab.counterfactual_runner import run_counterfactual_plan
from src.services.strategy_lab.rule_validation_contract import (
    CounterfactualKind,
    CounterfactualPlan,
    CounterfactualSpec,
    DatasetSplitContract,
    ExperimentBudget,
    ExperimentBudgetUsage,
    GateStatus,
    PITInputEvidence,
    RuleContract,
    RuleValidationContract,
    evaluate_rule_validation_preflight,
)
from src.services.strategy_lab.temporal_contract import TemporalEvidence, TemporalInterval

UTC = timezone.utc


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _interval(start: str, end: str) -> TemporalInterval:
    return TemporalInterval(_dt(start), _dt(end))


def _rule(**changes) -> RuleContract:
    values = {
        "rule_id": "rs-breakout",
        "rule_version": "v0.1",
        "hypothesis": "Persistent relative strength improves candidate precision.",
        "input_fields": ("relative_strength", "price_structure"),
        "applicable_regimes": ("risk_on", "neutral"),
        "trigger_contract": "relative_strength > threshold and structure == accepted",
        "expected_effect": "improve precision without unacceptable recall loss",
        "invalidation_contract": "edge disappears after costs or outside one year",
    }
    values.update(changes)
    return RuleContract(**values)


def _split(**changes) -> DatasetSplitContract:
    values = {
        "dataset_id": "a-share-pit-v1",
        "dataset_version": "sha256:dataset",
        "development": _interval("2020-01-01", "2022-01-01"),
        "validation": _interval("2022-02-01", "2023-01-01"),
        "never_seen_holdout": _interval("2023-02-01", "2024-01-01"),
        "embargo_bars": 20,
    }
    values.update(changes)
    return DatasetSplitContract(**values)


def _budget(**changes) -> ExperimentBudget:
    values = {
        "rule_family_id": "relative-strength",
        "max_trials": 12,
        "max_parameter_sets": 24,
        "max_model_calls": 4,
        "max_human_mutations": 3,
    }
    values.update(changes)
    return ExperimentBudget(**values)


def _plan(*, reverse: bool = False) -> CounterfactualPlan:
    variants = (
        CounterfactualSpec("with", CounterfactualKind.WITH_RULE),
        CounterfactualSpec("without", CounterfactualKind.WITHOUT_RULE),
        CounterfactualSpec("shuffle-7", CounterfactualKind.SHUFFLED_PLACEBO, deterministic_seed=7),
        CounterfactualSpec("delay-1", CounterfactualKind.DELAYED_RULE, delay_bars=1),
        CounterfactualSpec("risk-on", CounterfactualKind.REGIME_CONDITIONED, regime_id="risk_on"),
    )
    return CounterfactualPlan(tuple(reversed(variants)) if reverse else variants)


def _contract(**changes) -> RuleValidationContract:
    values = {
        "rule": _rule(),
        "dataset_split": _split(),
        "budget": _budget(),
        "counterfactual_plan": _plan(),
    }
    values.update(changes)
    return RuleValidationContract(**values)


def _manifest(contract: RuleValidationContract, **changes) -> ExperimentManifest:
    values = {
        "experiment_id": "exp-rs-001",
        "schema_version": "v1",
        "governed_components": contract.governed_components,
        "created_at": _dt("2026-09-13T00:00:00"),
        "root_experiment_id": "exp-rs-001",
        "parent_experiment_id": None,
    }
    values.update(changes)
    return ExperimentManifest(**values)


def _pit(*, unknown: str | None = None, late: str | None = None) -> tuple[PITInputEvidence, ...]:
    items = []
    for field_name in ("relative_strength", "price_structure"):
        temporal = TemporalEvidence(
            effective_at=_dt("2023-03-01"),
            available_at=(_dt("2024-02-01") if field_name == late else _dt("2023-03-02")),
        )
        items.append(
            PITInputEvidence(
                evidence_id=f"ev-{field_name}",
                field_name=field_name,
                temporal_evidence=None if field_name == unknown else temporal,
            )
        )
    return tuple(items)


def _preflight(
    contract: RuleValidationContract,
    manifest: ExperimentManifest,
    *,
    pit_evidence=None,
    usage=None,
    reservation=None,
):
    return evaluate_rule_validation_preflight(
        contract=contract,
        manifest=manifest,
        decision_time=_dt("2023-06-01"),
        pit_evidence=_pit() if pit_evidence is None else pit_evidence,
        budget_usage=usage or ExperimentBudgetUsage(trials=2, parameter_sets=4),
        budget_reservation=reservation or ExperimentBudgetUsage(trials=1, parameter_sets=2),
    )


def _gate(report, name: str):
    return next(result for result in report.gate_results if result.gate == name)


def test_rule_contract_canonicalizes_set_like_fields() -> None:
    first = _rule(
        input_fields=("price_structure", "relative_strength", "price_structure"),
        applicable_regimes=("neutral", "risk_on"),
    )
    second = _rule()
    assert first.input_fields == ("price_structure", "relative_strength")
    assert first.fingerprint == second.fingerprint


def test_rule_contract_cannot_drop_research_only_boundaries() -> None:
    with pytest.raises(ValueError, match="forbidden_uses"):
        _rule(forbidden_uses=("live_order_execution",))


def test_rule_contract_semantic_change_changes_fingerprint() -> None:
    assert _rule().fingerprint != _rule(hypothesis="A different hypothesis.").fingerprint


def test_dataset_split_rejects_validation_overlap() -> None:
    with pytest.raises(ValueError, match="development and validation"):
        _split(validation=_interval("2021-12-01", "2023-01-01"))


def test_dataset_split_rejects_holdout_overlap() -> None:
    with pytest.raises(ValueError, match="Never-Seen Holdout"):
        _split(never_seen_holdout=_interval("2022-12-01", "2024-01-01"))


def test_dataset_split_change_changes_fingerprint() -> None:
    assert _split().fingerprint != _split(embargo_bars=21).fingerprint


def test_budget_rejects_bool_and_zero_core_limits() -> None:
    with pytest.raises(ValueError, match="max_trials"):
        _budget(max_trials=True)
    with pytest.raises(ValueError, match="max_parameter_sets must be positive"):
        _budget(max_parameter_sets=0)


def test_counterfactual_plan_requires_all_families() -> None:
    variants = tuple(variant for variant in _plan().variants if variant.kind is not CounterfactualKind.DELAYED_RULE)
    with pytest.raises(ValueError, match="missing required kinds"):
        CounterfactualPlan(variants)


def test_counterfactual_variant_requires_deterministic_controls() -> None:
    with pytest.raises(ValueError, match="deterministic_seed"):
        CounterfactualSpec("shuffle", CounterfactualKind.SHUFFLED_PLACEBO)
    with pytest.raises(ValueError, match="positive delay_bars"):
        CounterfactualSpec("delay", CounterfactualKind.DELAYED_RULE, delay_bars=0)
    with pytest.raises(ValueError, match="regime_id"):
        CounterfactualSpec("regime", CounterfactualKind.REGIME_CONDITIONED)


def test_counterfactual_plan_is_order_invariant() -> None:
    assert _plan().variants == _plan(reverse=True).variants
    assert _plan().fingerprint == _plan(reverse=True).fingerprint


def test_governed_components_are_read_only_and_complete() -> None:
    components = _contract().governed_components
    assert set(components) == {
        "rule_contract",
        "dataset_split",
        "experiment_budget",
        "counterfactual_plan",
        "pit_policy",
        "rule_validation_contract",
    }
    with pytest.raises(TypeError):
        components["rule_contract"] = "mutated"


def test_preflight_passes_only_when_all_gates_pass() -> None:
    contract = _contract()
    report = _preflight(contract, _manifest(contract))
    assert report.eligible_for_holdout_claim is True
    assert [result.gate for result in report.gate_results] == [
        "manifest_binding",
        "dataset_split",
        "pit_anti_leak",
        "experiment_budget",
        "counterfactual_coverage",
    ]
    assert all(result.status is GateStatus.PASS for result in report.gate_results)


def test_missing_manifest_binding_is_unknown_and_blocks() -> None:
    contract = _contract()
    components = dict(contract.governed_components)
    components.pop("pit_policy")
    report = _preflight(contract, _manifest(contract, governed_components=components))
    gate = _gate(report, "manifest_binding")
    assert gate.status is GateStatus.UNKNOWN
    assert gate.evidence["missing_keys"] == ("pit_policy",)
    assert report.eligible_for_holdout_claim is False


def test_conflicting_manifest_binding_fails_and_dominates_missing() -> None:
    contract = _contract()
    components = dict(contract.governed_components)
    components["rule_contract"] = "wrong"
    components.pop("pit_policy")
    report = _preflight(contract, _manifest(contract, governed_components=components))
    gate = _gate(report, "manifest_binding")
    assert gate.status is GateStatus.FAIL
    assert gate.evidence["mismatched_keys"] == ("rule_contract",)
    assert report.eligible_for_holdout_claim is False


def test_unknown_pit_evidence_blocks() -> None:
    contract = _contract()
    report = _preflight(contract, _manifest(contract), pit_evidence=_pit(unknown="relative_strength"))
    gate = _gate(report, "pit_anti_leak")
    assert gate.status is GateStatus.UNKNOWN
    assert gate.evidence["unknown_fields"] == ("relative_strength",)
    assert report.eligible_for_holdout_claim is False


def test_missing_pit_field_is_unknown_not_silently_ignored() -> None:
    contract = _contract()
    evidence = tuple(item for item in _pit() if item.field_name != "price_structure")
    gate = _gate(_preflight(contract, _manifest(contract), pit_evidence=evidence), "pit_anti_leak")
    assert gate.status is GateStatus.UNKNOWN
    assert gate.evidence["unknown_fields"] == ("price_structure",)


def test_late_pit_evidence_fails() -> None:
    contract = _contract()
    report = _preflight(contract, _manifest(contract), pit_evidence=_pit(late="price_structure"))
    gate = _gate(report, "pit_anti_leak")
    assert gate.status is GateStatus.FAIL
    assert gate.evidence["late_fields"] == ("price_structure",)


def test_pit_evidence_rejects_duplicates_and_undeclared_fields() -> None:
    contract = _contract()
    duplicate = (_pit()[0], _pit()[0])
    with pytest.raises(ValueError, match="duplicate PIT evidence"):
        _preflight(contract, _manifest(contract), pit_evidence=duplicate)
    undeclared = (
        *_pit(),
        PITInputEvidence(
            "ev-future-news",
            "future_news",
            TemporalEvidence(_dt("2023-01-01"), _dt("2023-01-01")),
        ),
    )
    with pytest.raises(ValueError, match="undeclared input field"):
        _preflight(contract, _manifest(contract), pit_evidence=undeclared)


def test_budget_exact_boundary_passes() -> None:
    contract = _contract()
    report = _preflight(
        contract,
        _manifest(contract),
        usage=ExperimentBudgetUsage(trials=11, parameter_sets=23, model_calls=4, human_mutations=3),
        reservation=ExperimentBudgetUsage(trials=1, parameter_sets=1),
    )
    assert _gate(report, "experiment_budget").status is GateStatus.PASS


def test_budget_excess_fails_without_compensating_dimensions() -> None:
    contract = _contract()
    report = _preflight(
        contract,
        _manifest(contract),
        usage=ExperimentBudgetUsage(trials=12, parameter_sets=1),
        reservation=ExperimentBudgetUsage(trials=1),
    )
    gate = _gate(report, "experiment_budget")
    assert gate.status is GateStatus.FAIL
    assert gate.evidence["exceeded_dimensions"] == ("trials",)
    assert gate.evidence["snapshot_only"] is True
    assert report.eligible_for_holdout_claim is False


def test_contract_change_without_manifest_refresh_fails_binding() -> None:
    original = _contract()
    manifest = _manifest(original)
    changed = replace(original, budget=_budget(max_trials=13))
    gate = _gate(_preflight(changed, manifest), "manifest_binding")
    assert gate.status is GateStatus.FAIL
    assert "experiment_budget" in gate.evidence["mismatched_keys"]


def test_harness_schema_change_without_manifest_refresh_fails_binding() -> None:
    original = _contract()
    manifest = _manifest(original)
    changed = replace(original, schema_version="radar-rule-validation-harness-v0.2")
    gate = _gate(_preflight(changed, manifest), "manifest_binding")
    assert gate.status is GateStatus.FAIL
    assert gate.evidence["mismatched_keys"] == ("rule_validation_contract",)


def test_gate_evidence_is_deeply_read_only() -> None:
    contract = _contract()
    gate = _gate(_preflight(contract, _manifest(contract)), "experiment_budget")
    with pytest.raises(TypeError):
        gate.evidence["projected"]["trials"] = 999


def test_preflight_normalizes_decision_time_to_utc() -> None:
    contract = _contract()
    decision_time = datetime.fromisoformat("2023-06-01T09:00:00+09:00")
    report = evaluate_rule_validation_preflight(
        contract=contract,
        manifest=_manifest(contract),
        decision_time=decision_time,
        pit_evidence=_pit(),
        budget_usage=ExperimentBudgetUsage(),
        budget_reservation=ExperimentBudgetUsage(trials=1, parameter_sets=1),
    )
    assert report.decision_time.isoformat() == "2023-06-01T00:00:00+00:00"


def test_preflight_is_a_strategy_lab_leaf_without_runtime_or_repository_imports() -> None:
    path = Path("src/services/strategy_lab/rule_validation_contract.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden_prefixes = ("src.repositories", "src.storage", "data_provider", "realtime_monitor")
    assert not any(name.startswith(forbidden_prefixes) for name in imported)


def test_counterfactual_runner_executes_every_frozen_variant_once() -> None:
    plan = _plan()
    seen = []
    report = run_counterfactual_plan(
        plan, lambda variant: (seen.append(variant.variant_id) or {"alpha": 1.0})
    )
    assert report.plan_fingerprint == plan.fingerprint
    assert seen == [variant.variant_id for variant in plan.variants]
