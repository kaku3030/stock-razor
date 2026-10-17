"""Research-only assembly of a frozen Agent decision into the Observation Ledger.

This module is deliberately not a strategy, risk, portfolio, or execution
owner.  It accepts facts already produced by the caller and leaves unavailable
facts as ``None``/``UNKNOWN``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .observation_ledger import (
    OBSERVATION_CAPTURE_CONTRACT_VERSION,
    Observation,
    ObservationCaptureWriter,
    SourceEventAtQuality,
    LatencyTrace,
)


ASSEMBLY_CONTRACT_VERSION = "shadow-observation-assembly-v0.1"
DECISION_BOUNDARY = "agent_orchestrator.final_decision_risk_freeze"


@dataclass(frozen=True)
class ShadowObservationIdentity:
    """Stable identity inputs; no dashboard content is used as an ID."""

    run_id: str
    instrument: str
    decision_boundary: str = DECISION_BOUNDARY
    contract_version: str = ASSEMBLY_CONTRACT_VERSION

    def payload(self) -> dict[str, str]:
        values = {
            "contract_version": self.contract_version,
            "decision_boundary": self.decision_boundary,
            "instrument": self.instrument,
            "run_id": self.run_id,
        }
        if not all(values.values()):
            raise ValueError("observation identity requires run_id, instrument, and boundary")
        return values

    def observation_id(self) -> str:
        encoded = json.dumps(self.payload(), sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def assemble_shadow_observation(
    *,
    run_id: str,
    instrument: str,
    dashboard: Mapping[str, Any],
    evidence_ids: tuple[str, ...] = (),
    strategy_gate_results: Mapping[str, str] | None = None,
    timestamps: Mapping[str, Any] | None = None,
    writer: ObservationCaptureWriter | None = None,
) -> Observation:
    """Assemble one frozen decision without deriving missing semantics.

    ``dashboard`` is accepted as an audit reference only.  Its signal/risk
    values are intentionally not mapped into portfolio or execution fields.
    ``timestamps`` must be supplied by an upstream producer; this function
    never calls the clock or infers causal times from stage completion.
    """
    identity = ShadowObservationIdentity(run_id=run_id.strip(), instrument=instrument.strip())
    raw_times = dict(timestamps or {})
    quality = SourceEventAtQuality(raw_times.get("source_event_at_quality") or SourceEventAtQuality.UNKNOWN)
    if quality is SourceEventAtQuality.UNKNOWN:
        raw_times["source_event_at"] = None

    latency = LatencyTrace(
        source_event_at=raw_times.get("source_event_at"),
        source_event_at_quality=quality,
        data_received_at=raw_times.get("data_received_at"),
        knowledge_available_at=raw_times.get("knowledge_available_at"),
        detected_at=raw_times.get("detected_at"),
        strategy_decided_at=raw_times.get("strategy_decided_at"),
        risk_decided_at=raw_times.get("risk_decided_at"),
        execution_ready_at=raw_times.get("execution_ready_at"),
        order_sent_at=raw_times.get("order_sent_at"),
        fill_at=raw_times.get("fill_at"),
    )
    observation = Observation(
        observation_id=identity.observation_id(),
        detector_status="DECISION_FROZEN",
        evidence_ids=tuple(evidence_ids),
        strategy_gate_results=dict(strategy_gate_results or {}),
        decision_available_at=raw_times.get("decision_available_at"),
        canonical_permission="UNKNOWN",
        latency=latency,
    )
    if writer is not None:
        writer.append(
            observation,
            source_type=ASSEMBLY_CONTRACT_VERSION,
            instrument=instrument,
            provenance={
                "assembly_contract_version": ASSEMBLY_CONTRACT_VERSION,
                "identity_payload": identity.payload(),
                "ledger_contract_version": OBSERVATION_CAPTURE_CONTRACT_VERSION,
                "dashboard_reference": "frozen_final_dashboard",
            },
        )
    return observation
