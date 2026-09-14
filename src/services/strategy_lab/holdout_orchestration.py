"""Narrow Reservation -> OOS Ledger bridge for research-only experiments."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Sequence

from .experiment_governance import ExperimentManifest
from .oos_consumption import OOSClaimResult
from .research_dataset import ResearchDatasetCapsule
from .rule_validation_contract import RuleValidationContract
from .temporal_contract import canonical_utc_datetime

if TYPE_CHECKING:
    from src.repositories.experiment_registry_repo import ExperimentRegistryRepository
    from src.repositories.oos_consumption_ledger_repo import OOSConsumptionLedgerRepository


@dataclass(frozen=True)
class HoldoutClaimOrchestrationResult:
    reservation_operation_id: str
    claim_result: OOSClaimResult | None
    blocked_reason: str | None


class ReservedHoldoutClaimOrchestrator:
    """Requires an already committed reservation before an OOS claim.

    Reservation deliberately precedes the irreversible OOS claim. If the OOS
    Ledger denies a claim, budget stays consumed: this is conservative and
    cannot create a retry path around the experiment budget.
    """
    def __init__(self, registry: ExperimentRegistryRepository, ledger: OOSConsumptionLedgerRepository):
        self.registry, self.ledger = registry, ledger

    def claim(self, *, reservation_operation_id: str, claim_operation_id: str,
              manifest: ExperimentManifest, contract: RuleValidationContract,
              dataset: ResearchDatasetCapsule, lineage_history: Sequence[ExperimentManifest] = (),
              declared_at: datetime) -> HoldoutClaimOrchestrationResult:
        reservation = self.registry.get_registration(operation_id=reservation_operation_id)
        if reservation is None:
            return HoldoutClaimOrchestrationResult(reservation_operation_id, None, "reservation_not_found")
        if reservation.experiment_id != manifest.experiment_id or reservation.manifest_hash != manifest.manifest_hash:
            return HoldoutClaimOrchestrationResult(reservation_operation_id, None, "reservation_manifest_mismatch")
        if reservation.contract_fingerprint != contract.fingerprint:
            return HoldoutClaimOrchestrationResult(reservation_operation_id, None, "reservation_contract_mismatch")
        split = contract.dataset_split
        if (dataset.dataset_id, dataset.dataset_version) != (split.dataset_id, split.dataset_version):
            return HoldoutClaimOrchestrationResult(reservation_operation_id, None, "dataset_binding_mismatch")
        result = self.ledger.claim_if_pristine(
            operation_id=claim_operation_id, target_manifest=manifest,
            lineage_history=lineage_history, oos_interval=split.never_seen_holdout,
            declared_occurred_at=canonical_utc_datetime(declared_at),
        )
        return HoldoutClaimOrchestrationResult(reservation_operation_id, result, None)
