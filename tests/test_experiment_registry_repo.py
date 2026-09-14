"""Adversarial persistence tests for the Rule Validation Harness registry."""

import os
import tempfile
import threading
import time
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select

from src.repositories.experiment_registry_repo import ExperimentRegistryRepository
from src.repositories.oos_consumption_ledger_repo import OOSConsumptionLedgerRepository
from src.services.strategy_lab.experiment_governance import ExperimentManifest
from src.services.strategy_lab.experiment_registry import (
    ExperimentRegistrationStatus,
    ExperimentRegistryBudgetPolicyConflictError,
    ExperimentRegistryIdempotencyConflictError,
    ExperimentRegistryIdentityConflictError,
)
from src.services.strategy_lab.holdout_orchestration import ReservedHoldoutClaimOrchestrator
from src.services.strategy_lab.oos_consumption import OOSClaimStatus
from src.services.strategy_lab.research_dataset import LateEventPolicy, ResearchDataEvent, ResearchDatasetCapsule
from src.services.strategy_lab.rule_validation_contract import (
    CounterfactualKind,
    CounterfactualPlan,
    CounterfactualSpec,
    DatasetSplitContract,
    ExperimentBudget,
    ExperimentBudgetUsage,
    PITInputEvidence,
    RuleContract,
    RuleValidationContract,
)
from src.services.strategy_lab.temporal_contract import TemporalEvidence, TemporalInterval
from src.storage import (
    CURRENT_SCHEMA_VERSION,
    DatabaseManager,
    ExperimentBudgetPolicyRecord,
    ExperimentRegistryReservationRecord,
    OOSConsumptionEventRecord,
)

UTC = timezone.utc


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _contract(*, family: str = "rs-breakout", max_trials: int = 3) -> RuleValidationContract:
    return RuleValidationContract(
        rule=RuleContract(
            rule_id="rs-breakout", rule_version="v1", hypothesis="relative strength persists",
            input_fields=("close",), applicable_regimes=("risk_on",),
            trigger_contract="close above base", expected_effect="positive excess return",
            invalidation_contract="relative strength collapses",
        ),
        dataset_split=DatasetSplitContract(
            dataset_id="us-eod", dataset_version="2026-09-13",
            development=TemporalInterval(_dt("2020-01-01"), _dt("2022-01-01")),
            validation=TemporalInterval(_dt("2022-01-01"), _dt("2023-01-01")),
            never_seen_holdout=TemporalInterval(_dt("2023-01-01"), _dt("2024-01-01")),
        ),
        budget=ExperimentBudget(
            rule_family_id=family, max_trials=max_trials, max_parameter_sets=6,
            max_model_calls=2, max_human_mutations=1,
        ),
        counterfactual_plan=CounterfactualPlan(variants=(
            CounterfactualSpec("with", CounterfactualKind.WITH_RULE),
            CounterfactualSpec("without", CounterfactualKind.WITHOUT_RULE),
            CounterfactualSpec("shuffle", CounterfactualKind.SHUFFLED_PLACEBO, deterministic_seed=7),
            CounterfactualSpec("delay", CounterfactualKind.DELAYED_RULE, delay_bars=1),
            CounterfactualSpec("regime", CounterfactualKind.REGIME_CONDITIONED, regime_id="risk_on"),
        )),
    )


def _manifest(experiment_id: str, contract: RuleValidationContract) -> ExperimentManifest:
    return ExperimentManifest(
        experiment_id=experiment_id,
        schema_version="v1",
        governed_components=contract.governed_components,
        created_at=_dt("2024-01-01"),
        root_experiment_id=experiment_id,
    )


def _pit(*, available: bool = True) -> tuple[PITInputEvidence, ...]:
    instant = _dt("2024-02-01") if available else _dt("2024-02-03")
    return (PITInputEvidence("close-eod", "close", TemporalEvidence(instant, instant)),)


def _reserve(repo, *, operation_id: str, experiment_id: str, contract=None, reservation=None, pit=None):
    contract = contract or _contract()
    return repo.preflight_and_reserve(
        operation_id=operation_id,
        manifest=_manifest(experiment_id, contract),
        contract=contract,
        decision_time=_dt("2024-02-02"),
        pit_evidence=_pit() if pit is None else pit,
        reservation=reservation or ExperimentBudgetUsage(trials=1, parameter_sets=1),
        declared_at=_dt("2024-02-02"),
    )


def setup_function() -> None:
    DatabaseManager.reset_instance()


def teardown_function() -> None:
    DatabaseManager.reset_instance()


@pytest.fixture()
def repo() -> ExperimentRegistryRepository:
    DatabaseManager("sqlite:///:memory:")
    return ExperimentRegistryRepository()


def test_reservation_is_persistent_and_consumes_budget(repo) -> None:
    result = _reserve(repo, operation_id="op-1", experiment_id="E1")
    assert result.status is ExperimentRegistrationStatus.RESERVED
    assert result.usage_before == ExperimentBudgetUsage()
    assert result.usage_after == ExperimentBudgetUsage(trials=1, parameter_sets=1)
    assert result.registration.experiment_id == "E1"
    assert repo.get_usage(rule_family_id="rs-breakout") == ExperimentBudgetUsage(trials=1, parameter_sets=1)
    assert tuple(item.experiment_id for item in repo.list_registrations()) == ("E1",)


def test_budget_exhaustion_leaves_no_partial_registration(repo) -> None:
    contract = _contract(max_trials=1)
    assert _reserve(repo, operation_id="op-1", experiment_id="E1", contract=contract).status is ExperimentRegistrationStatus.RESERVED
    rejected = _reserve(repo, operation_id="op-2", experiment_id="E2", contract=contract)
    assert rejected.status is ExperimentRegistrationStatus.BUDGET_EXHAUSTED
    assert rejected.registration is None
    assert tuple(item.experiment_id for item in repo.list_registrations()) == ("E1",)


def test_pit_block_leaves_no_policy_or_registration(repo) -> None:
    result = _reserve(repo, operation_id="op-1", experiment_id="E1", pit=_pit(available=False))
    assert result.status is ExperimentRegistrationStatus.PREFLIGHT_BLOCKED
    with repo.db.get_session() as session:
        assert session.execute(select(ExperimentBudgetPolicyRecord)).scalars().all() == []
        assert session.execute(select(ExperimentRegistryReservationRecord)).scalars().all() == []


def test_same_operation_replays_without_new_budget_consumption(repo) -> None:
    first = _reserve(repo, operation_id="op-1", experiment_id="E1")
    replay = _reserve(repo, operation_id="op-1", experiment_id="E1")
    assert first.status is ExperimentRegistrationStatus.RESERVED
    assert replay.status is ExperimentRegistrationStatus.IDEMPOTENT_REPLAY
    assert replay.registration.registration_id == first.registration.registration_id
    assert repo.get_usage(rule_family_id="rs-breakout") == ExperimentBudgetUsage(trials=1, parameter_sets=1)


def test_idempotent_replay_at_exact_budget_limit_keeps_passing_preflight(repo) -> None:
    contract = _contract(max_trials=1)
    _reserve(repo, operation_id="op-1", experiment_id="E1", contract=contract)
    replay = _reserve(repo, operation_id="op-1", experiment_id="E1", contract=contract)
    assert replay.status is ExperimentRegistrationStatus.IDEMPOTENT_REPLAY
    assert replay.preflight_report.eligible_for_holdout_claim is True


def test_operation_id_payload_change_is_conflict(repo) -> None:
    _reserve(repo, operation_id="op-1", experiment_id="E1")
    with pytest.raises(ExperimentRegistryIdempotencyConflictError):
        _reserve(repo, operation_id="op-1", experiment_id="E1", reservation=ExperimentBudgetUsage(trials=2, parameter_sets=2))


def test_experiment_identity_is_one_immutable_registration(repo) -> None:
    _reserve(repo, operation_id="op-1", experiment_id="E1")
    with pytest.raises(ExperimentRegistryIdentityConflictError):
        _reserve(repo, operation_id="op-2", experiment_id="E1")


def test_rule_family_budget_policy_cannot_be_rewritten(repo) -> None:
    _reserve(repo, operation_id="op-1", experiment_id="E1", contract=_contract(max_trials=3))
    with pytest.raises(ExperimentRegistryBudgetPolicyConflictError):
        _reserve(repo, operation_id="op-2", experiment_id="E2", contract=_contract(max_trials=4))


def test_registry_never_claims_or_burns_oos(repo) -> None:
    _reserve(repo, operation_id="op-1", experiment_id="E1")
    with repo.db.get_session() as session:
        assert session.execute(select(OOSConsumptionEventRecord)).scalars().all() == []


def test_only_matching_reserved_dataset_can_claim_holdout(repo) -> None:
    contract = _contract()
    manifest = _manifest("E1", contract)
    _reserve(repo, operation_id="reserve-1", experiment_id="E1", contract=contract)
    dataset = ResearchDatasetCapsule(
        dataset_id="us-eod", dataset_version="2026-09-13", source_id="fixture",
        adapter_version="v1", late_event_policy=LateEventPolicy.DROP,
        events=(ResearchDataEvent("bar-1", "source-1", "a" * 64, _dt("2023-01-02"),
                                  _dt("2023-01-02"), _dt("2023-01-02"), 0),),
    )
    result = ReservedHoldoutClaimOrchestrator(repo, OOSConsumptionLedgerRepository()).claim(
        reservation_operation_id="reserve-1", claim_operation_id="claim-1", manifest=manifest,
        contract=contract, dataset=dataset, declared_at=_dt("2024-02-02"),
    )
    assert result.blocked_reason is None
    assert result.claim_result.status is OOSClaimStatus.CLAIMED


def test_dataset_mismatch_cannot_claim_holdout(repo) -> None:
    contract = _contract()
    _reserve(repo, operation_id="reserve-1", experiment_id="E1", contract=contract)
    wrong = ResearchDatasetCapsule(
        "other", "v1", "fixture", "v1", LateEventPolicy.DROP,
        (ResearchDataEvent("bar-1", "source-1", "a" * 64, _dt("2023-01-02"),
                           _dt("2023-01-02"), _dt("2023-01-02"), 0),),
    )
    result = ReservedHoldoutClaimOrchestrator(repo, OOSConsumptionLedgerRepository()).claim(
        reservation_operation_id="reserve-1", claim_operation_id="claim-1", manifest=_manifest("E1", contract),
        contract=contract, dataset=wrong, declared_at=_dt("2024-02-02"),
    )
    assert result.claim_result is None and result.blocked_reason == "dataset_binding_mismatch"


def test_malformed_registry_schema_fails_closed_without_migration_stamp() -> None:
    temp_dir = tempfile.TemporaryDirectory()
    db_path = os.path.join(temp_dir.name, "malformed_registry.db")
    try:
        engine = create_engine(f"sqlite:///{db_path}")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE experiment_registry_reservation_records "
                "(registration_id INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT)"
            )
        engine.dispose()
        with pytest.raises(RuntimeError, match="Rule Validation Harness registry schema validation failed"):
            DatabaseManager(f"sqlite:///{db_path}")
        verify = create_engine(f"sqlite:///{db_path}")
        with verify.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT version FROM schema_migrations WHERE version=:version",
                {"version": CURRENT_SCHEMA_VERSION},
            ).all()
        verify.dispose()
        assert rows == []
    finally:
        DatabaseManager.reset_instance()
        temp_dir.cleanup()


def test_concurrent_reservations_serialize_on_real_sqlite_writer_lock() -> None:
    temp_dir = tempfile.TemporaryDirectory()
    db_path = os.path.join(temp_dir.name, "registry.db")
    try:
        DatabaseManager(f"sqlite:///{db_path}")
        repo = ExperimentRegistryRepository()
        contract = _contract(max_trials=1)
        started_a, started_b = threading.Event(), threading.Event()
        done_a, done_b = threading.Event(), threading.Event()
        results, errors = {}, []

        def worker(operation_id, experiment_id, started, done):
            try:
                started.set()
                results[operation_id] = _reserve(repo, operation_id=operation_id, experiment_id=experiment_id, contract=contract)
            except Exception as exc:  # pragma: no cover - diagnostic path
                errors.append(exc)
            finally:
                done.set()

        lock_session = repo.db.get_session()
        lock_session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        try:
            threads = [
                threading.Thread(target=worker, args=("op-a", "EA", started_a, done_a)),
                threading.Thread(target=worker, args=("op-b", "EB", started_b, done_b)),
            ]
            for thread in threads:
                thread.start()
            assert started_a.wait(10) and started_b.wait(10)
            time.sleep(0.2)
            assert not done_a.is_set() and not done_b.is_set()
        finally:
            lock_session.rollback()
            lock_session.close()
        for thread in threads:
            thread.join(30)
        assert errors == []
        assert {results["op-a"].status, results["op-b"].status} == {
            ExperimentRegistrationStatus.RESERVED, ExperimentRegistrationStatus.BUDGET_EXHAUSTED,
        }
        assert len(repo.list_registrations()) == 1
    finally:
        DatabaseManager.reset_instance()
        temp_dir.cleanup()
