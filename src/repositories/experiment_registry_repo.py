"""Atomic persistent registry for Rule Validation Harness experiments.

The registry owns the *research budget reservation*, not the Never-Seen
Holdout.  ``OOSConsumptionLedgerRepository`` remains the only component that
may claim or burn a holdout interval.

Successful registrations are append-only and budget-consuming.  Every
preflight, aggregate read, policy registration, and reservation insert occurs
inside one ``BEGIN IMMEDIATE`` transaction on SQLite, so concurrent requests
cannot both observe the same remaining budget.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.services.strategy_lab.experiment_governance import ExperimentManifest
from src.services.strategy_lab.experiment_registry import (
    ExperimentRegistration,
    ExperimentRegistrationResult,
    ExperimentRegistrationStatus,
    ExperimentRegistryBudgetPolicyConflictError,
    ExperimentRegistryIdempotencyConflictError,
    ExperimentRegistryIdentityConflictError,
    compute_registration_operation_fingerprint,
)
from src.services.strategy_lab.rule_validation_contract import (
    ExperimentBudgetUsage,
    GateStatus,
    PITInputEvidence,
    RuleValidationContract,
    evaluate_rule_validation_preflight,
)
from src.services.strategy_lab.oos_consumption import parse_aware_utc_text
from src.services.strategy_lab.temporal_contract import canonical_utc_datetime, canonical_utc_text
from src.storage import (
    DatabaseManager,
    ExperimentBudgetPolicyRecord,
    ExperimentRegistryReservationRecord,
)


def _require_identity(label: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string, got {value!r}")
    return value.strip()


def _now_utc_text() -> str:
    return canonical_utc_text(datetime.now(timezone.utc))


def _usage_from_row(row: ExperimentRegistryReservationRecord) -> ExperimentBudgetUsage:
    return ExperimentBudgetUsage(
        trials=row.reserved_trials,
        parameter_sets=row.reserved_parameter_sets,
        model_calls=row.reserved_model_calls,
        human_mutations=row.reserved_human_mutations,
    )


def _subtract_usage(total: ExperimentBudgetUsage, reservation: ExperimentBudgetUsage) -> ExperimentBudgetUsage:
    """Recover the replay's pre-reservation snapshot without underflow."""

    values = tuple(
        getattr(total, field_name) - getattr(reservation, field_name)
        for field_name in ("trials", "parameter_sets", "model_calls", "human_mutations")
    )
    if any(value < 0 for value in values):
        raise RuntimeError("persisted experiment budget usage is internally inconsistent")
    return ExperimentBudgetUsage(*values)


def _registration_from_row(row: ExperimentRegistryReservationRecord) -> ExperimentRegistration:
    return ExperimentRegistration(
        registration_id=row.registration_id,
        operation_id=row.operation_id,
        experiment_id=row.experiment_id,
        manifest_hash=row.manifest_hash,
        contract_fingerprint=row.contract_fingerprint,
        rule_family_id=row.rule_family_id,
        budget_fingerprint=row.budget_fingerprint,
        reservation=_usage_from_row(row),
        decision_time=parse_aware_utc_text(row.decision_time_utc_text),
        declared_at=parse_aware_utc_text(row.declared_at_utc_text),
        recorded_at=parse_aware_utc_text(row.recorded_at_utc_text),
    )


def _pit_evidence_fingerprint(evidence_items: Sequence[PITInputEvidence]) -> str:
    """Stable identity of caller-supplied PIT evidence, excluding budget state."""

    payload = []
    for item in evidence_items:
        if not isinstance(item, PITInputEvidence):
            raise ValueError("pit_evidence must contain only PITInputEvidence")
        temporal = item.temporal_evidence
        payload.append({
            "evidence_id": item.evidence_id,
            "field_name": item.field_name,
            "effective_at": canonical_utc_text(temporal.effective_at) if temporal else None,
            "available_at": canonical_utc_text(temporal.available_at) if temporal else None,
        })
    payload.sort(key=lambda item: (item["field_name"], item["evidence_id"]))
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ExperimentRegistryRepository:
    """Append-only registry with immutable rule-family budget policies."""

    def __init__(self, db_manager: DatabaseManager | None = None):
        self.db = db_manager or DatabaseManager.get_instance()
        ExperimentBudgetPolicyRecord.__table__.create(self.db._engine, checkfirst=True)
        ExperimentRegistryReservationRecord.__table__.create(self.db._engine, checkfirst=True)

    def get_usage(self, *, rule_family_id: str) -> ExperimentBudgetUsage:
        rule_family_id = _require_identity("rule_family_id", rule_family_id)
        with self.db.get_session() as session:
            return self._usage(session, rule_family_id)

    def get_registration(self, *, operation_id: str) -> ExperimentRegistration | None:
        operation_id = _require_identity("operation_id", operation_id)
        with self.db.get_session() as session:
            row = session.execute(select(ExperimentRegistryReservationRecord).where(
                ExperimentRegistryReservationRecord.operation_id == operation_id
            )).scalar_one_or_none()
            return _registration_from_row(row) if row is not None else None

    def list_registrations(
        self, *, rule_family_id: str | None = None, limit: int = 500
    ) -> tuple[ExperimentRegistration, ...]:
        if rule_family_id is not None:
            rule_family_id = _require_identity("rule_family_id", rule_family_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive int")
        with self.db.get_session() as session:
            statement = select(ExperimentRegistryReservationRecord).order_by(
                ExperimentRegistryReservationRecord.registration_id.asc()
            )
            if rule_family_id is not None:
                statement = statement.where(ExperimentRegistryReservationRecord.rule_family_id == rule_family_id)
            return tuple(_registration_from_row(row) for row in session.execute(statement.limit(limit)).scalars())

    def preflight_and_reserve(
        self,
        *,
        operation_id: str,
        manifest: ExperimentManifest,
        contract: RuleValidationContract,
        decision_time: datetime,
        pit_evidence: Sequence[PITInputEvidence],
        reservation: ExperimentBudgetUsage,
        declared_at: datetime,
    ) -> ExperimentRegistrationResult:
        operation_id = _require_identity("operation_id", operation_id)
        if not isinstance(manifest, ExperimentManifest):
            raise ValueError("manifest must be ExperimentManifest")
        if not isinstance(contract, RuleValidationContract):
            raise ValueError("contract must be RuleValidationContract")
        if not isinstance(reservation, ExperimentBudgetUsage):
            raise ValueError("reservation must be ExperimentBudgetUsage")
        decision_time = canonical_utc_datetime(decision_time)
        declared_at = canonical_utc_datetime(declared_at)
        pit_evidence_fingerprint = _pit_evidence_fingerprint(pit_evidence)

        def _write(session: Session) -> ExperimentRegistrationResult:
            operation_fingerprint = compute_registration_operation_fingerprint(
                experiment_id=manifest.experiment_id,
                manifest_hash=manifest.manifest_hash,
                contract_fingerprint=contract.fingerprint,
                rule_family_id=contract.budget.rule_family_id,
                budget_fingerprint=contract.budget.fingerprint,
                reservation=reservation,
                pit_evidence_fingerprint=pit_evidence_fingerprint,
                decision_time=decision_time,
                declared_at=declared_at,
            )
            replay = session.execute(
                select(ExperimentRegistryReservationRecord).where(
                    ExperimentRegistryReservationRecord.operation_id == operation_id
                )
            ).scalar_one_or_none()
            if replay is not None:
                if replay.operation_fingerprint != operation_fingerprint:
                    raise ExperimentRegistryIdempotencyConflictError(
                        f"operation_id {operation_id!r} was already registered with another semantic request"
                    )
                current_usage = self._usage(session, contract.budget.rule_family_id)
                usage_before = _subtract_usage(current_usage, _usage_from_row(replay))
                report = evaluate_rule_validation_preflight(
                    contract=contract, manifest=manifest, decision_time=decision_time,
                    pit_evidence=pit_evidence, budget_usage=usage_before,
                    budget_reservation=reservation,
                )
                return ExperimentRegistrationResult(
                    operation_id=operation_id,
                    status=ExperimentRegistrationStatus.IDEMPOTENT_REPLAY,
                    preflight_report=report,
                    usage_before=current_usage,
                    usage_after=current_usage,
                    registration=_registration_from_row(replay),
                )

            usage_before = self._usage(session, contract.budget.rule_family_id)
            report = evaluate_rule_validation_preflight(
                contract=contract,
                manifest=manifest,
                decision_time=decision_time,
                pit_evidence=pit_evidence,
                budget_usage=usage_before,
                budget_reservation=reservation,
            )

            existing_experiment = session.execute(
                select(ExperimentRegistryReservationRecord).where(
                    ExperimentRegistryReservationRecord.experiment_id == manifest.experiment_id
                )
            ).scalar_one_or_none()
            if existing_experiment is not None:
                raise ExperimentRegistryIdentityConflictError(
                    f"experiment_id {manifest.experiment_id!r} is already registered and immutable"
                )

            budget_gate = next(gate for gate in report.gate_results if gate.gate == "experiment_budget")
            non_budget_blocked = any(
                gate.status is not GateStatus.PASS and gate.gate != "experiment_budget"
                for gate in report.gate_results
            )
            if non_budget_blocked:
                return ExperimentRegistrationResult(
                    operation_id, ExperimentRegistrationStatus.PREFLIGHT_BLOCKED, report,
                    usage_before, usage_before, None,
                )
            if budget_gate.status is not GateStatus.PASS:
                return ExperimentRegistrationResult(
                    operation_id, ExperimentRegistrationStatus.BUDGET_EXHAUSTED, report,
                    usage_before, usage_before, None,
                )

            self._register_or_verify_budget_policy(session, contract)
            record = ExperimentRegistryReservationRecord(
                operation_id=operation_id,
                operation_fingerprint=operation_fingerprint,
                experiment_id=manifest.experiment_id,
                manifest_hash=manifest.manifest_hash,
                contract_fingerprint=contract.fingerprint,
                rule_family_id=contract.budget.rule_family_id,
                budget_fingerprint=contract.budget.fingerprint,
                reserved_trials=reservation.trials,
                reserved_parameter_sets=reservation.parameter_sets,
                reserved_model_calls=reservation.model_calls,
                reserved_human_mutations=reservation.human_mutations,
                decision_time_utc_text=canonical_utc_text(decision_time),
                declared_at_utc_text=canonical_utc_text(declared_at),
                recorded_at_utc_text=_now_utc_text(),
            )
            session.add(record)
            session.flush()
            usage_after = usage_before.plus(reservation)
            return ExperimentRegistrationResult(
                operation_id, ExperimentRegistrationStatus.RESERVED, report,
                usage_before, usage_after, _registration_from_row(record),
            )

        return self.db._run_write_transaction("rule validation preflight_and_reserve", _write)

    @staticmethod
    def _usage(session: Session, rule_family_id: str) -> ExperimentBudgetUsage:
        values = session.execute(
            select(
                func.coalesce(func.sum(ExperimentRegistryReservationRecord.reserved_trials), 0),
                func.coalesce(func.sum(ExperimentRegistryReservationRecord.reserved_parameter_sets), 0),
                func.coalesce(func.sum(ExperimentRegistryReservationRecord.reserved_model_calls), 0),
                func.coalesce(func.sum(ExperimentRegistryReservationRecord.reserved_human_mutations), 0),
            ).where(ExperimentRegistryReservationRecord.rule_family_id == rule_family_id)
        ).one()
        return ExperimentBudgetUsage(*(int(value) for value in values))

    @staticmethod
    def _register_or_verify_budget_policy(session: Session, contract: RuleValidationContract) -> None:
        budget = contract.budget
        existing = session.get(ExperimentBudgetPolicyRecord, budget.rule_family_id)
        if existing is None:
            session.add(ExperimentBudgetPolicyRecord(
                rule_family_id=budget.rule_family_id,
                budget_fingerprint=budget.fingerprint,
                max_trials=budget.max_trials,
                max_parameter_sets=budget.max_parameter_sets,
                max_model_calls=budget.max_model_calls,
                max_human_mutations=budget.max_human_mutations,
                registered_at_utc_text=_now_utc_text(),
            ))
            return
        actual = (
            existing.budget_fingerprint, existing.max_trials, existing.max_parameter_sets,
            existing.max_model_calls, existing.max_human_mutations,
        )
        expected = (
            budget.fingerprint, budget.max_trials, budget.max_parameter_sets,
            budget.max_model_calls, budget.max_human_mutations,
        )
        if actual != expected:
            raise ExperimentRegistryBudgetPolicyConflictError(
                f"rule_family_id {budget.rule_family_id!r} already has a different frozen budget policy"
            )
