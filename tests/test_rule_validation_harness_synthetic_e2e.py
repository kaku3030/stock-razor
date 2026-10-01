"""Synthetic-fixture-only E2E proof for the Rule Validation Harness.

This proves orchestration integrity, never market efficacy.  No approved EOD
OHLCV CSV is present in this runtime, so this test has no production, live,
or real-data authority.
"""
from datetime import datetime, timezone

from src.repositories.experiment_registry_repo import ExperimentRegistryRepository
from src.repositories.oos_consumption_ledger_repo import OOSConsumptionLedgerRepository
from src.services.strategy_lab.counterfactual_runner import run_counterfactual_plan
from src.services.strategy_lab.experiment_governance import ExperimentManifest
from src.services.strategy_lab.holdout_orchestration import ReservedHoldoutClaimOrchestrator
from src.services.strategy_lab.oos_consumption import OOSBurnStatus, OOSClaimStatus, OOSConsumptionState
from src.services.strategy_lab.research_dataset import LateEventPolicy, ResearchDataEvent, ResearchDatasetCapsule
from src.services.strategy_lab.rule_validation_contract import (
    CounterfactualKind, CounterfactualPlan, CounterfactualSpec, DatasetSplitContract,
    ExperimentBudget, ExperimentBudgetUsage, PITInputEvidence, RuleContract, RuleValidationContract,
)
from src.services.strategy_lab.temporal_contract import TemporalEvidence, TemporalInterval
from src.storage import DatabaseManager

UTC = timezone.utc


def dt(value):
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def test_synthetic_fixture_e2e_is_consumed_but_not_promoted():
    DatabaseManager.reset_instance()
    DatabaseManager("sqlite:///:memory:")
    try:
        contract = RuleValidationContract(
            RuleContract("rs-breakout", "synthetic-v1", "RS persists", ("close",), ("risk_on",), "breakout", "alpha", "RS fails"),
            DatasetSplitContract("synthetic-us-eod", "fixture-v1", TemporalInterval(dt("2020-01-01"), dt("2022-01-01")), TemporalInterval(dt("2022-01-01"), dt("2023-01-01")), TemporalInterval(dt("2023-01-01"), dt("2024-01-01"))),
            ExperimentBudget("rs-breakout", 1, 1, 0, 0),
            CounterfactualPlan((CounterfactualSpec("with", CounterfactualKind.WITH_RULE), CounterfactualSpec("without", CounterfactualKind.WITHOUT_RULE), CounterfactualSpec("shuffle", CounterfactualKind.SHUFFLED_PLACEBO, deterministic_seed=7), CounterfactualSpec("delay", CounterfactualKind.DELAYED_RULE, delay_bars=1), CounterfactualSpec("regime", CounterfactualKind.REGIME_CONDITIONED, regime_id="risk_on"))),
        )
        manifest = ExperimentManifest("synthetic-rs-e2e", "v1", contract.governed_components, dt("2024-01-01"), "synthetic-rs-e2e")
        capsule = ResearchDatasetCapsule("synthetic-us-eod", "fixture-v1", "synthetic-fixture", "v1", LateEventPolicy.DROP, (
            ResearchDataEvent("e1", "s1", "a" * 64, dt("2020-01-01"), dt("2020-01-01"), dt("2020-01-01"), 0),
            ResearchDataEvent("e2", "s2", "b" * 64, dt("2023-01-02"), dt("2023-01-02"), dt("2023-01-02"), 1),
        ))
        registry, ledger = ExperimentRegistryRepository(), OOSConsumptionLedgerRepository()
        reservation = registry.preflight_and_reserve(operation_id="reserve", manifest=manifest, contract=contract, decision_time=dt("2024-01-02"), pit_evidence=(PITInputEvidence("close", "close", TemporalEvidence(dt("2024-01-01"), dt("2024-01-01"))),), reservation=ExperimentBudgetUsage(trials=1, parameter_sets=1), declared_at=dt("2024-01-02"))
        assert reservation.status.value == "reserved"
        claim = ReservedHoldoutClaimOrchestrator(registry, ledger).claim(reservation_operation_id="reserve", claim_operation_id="claim", manifest=manifest, contract=contract, dataset=capsule, declared_at=dt("2024-01-02"))
        assert claim.claim_result.status is OOSClaimStatus.CLAIMED
        report = run_counterfactual_plan(contract.counterfactual_plan, lambda variant: {"synthetic_metric": float(len(variant.variant_id))})
        assert len(report.measurements) == 5
        burned = ledger.mark_outcome_used(operation_id="outcome", target_manifest=manifest, oos_interval=contract.dataset_split.never_seen_holdout, declared_occurred_at=dt("2024-01-03"))
        assert burned.status is OOSBurnStatus.BURNED
        assert ledger.get_assessment(experiment_id=manifest.experiment_id, oos_interval=contract.dataset_split.never_seen_holdout).state is OOSConsumptionState.BURNED
    finally:
        DatabaseManager.reset_instance()
