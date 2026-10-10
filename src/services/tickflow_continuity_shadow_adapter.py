"""Read-only adapter from continuity evidence to TickFlow Shadow payloads.

The adapter derives only the continuity gate and latest observation metadata.
It preserves all other provider gates and never authorizes a source.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .tickflow_continuity_audit import (
    TickflowContinuityAudit,
    TickflowObservation,
    audit_tickflow_continuity,
)


@dataclass(frozen=True)
class TickflowContinuityEnvelope:
    payload: dict[str, Any]
    audit: TickflowContinuityAudit


def apply_tickflow_continuity_evidence(
    payload: dict[str, Any],
    observations: tuple[TickflowObservation, ...],
    *,
    now_utc,
    max_age_seconds: float,
    require_contiguous_sequence: bool = True,
) -> TickflowContinuityEnvelope:
    """Return a copied payload with a derived continuity gate.

    A failed audit becomes an explicit FAIL gate, so the existing Shadow
    arbiter rejects the candidate. No other qualification gate is upgraded.
    """
    audit = audit_tickflow_continuity(
        observations,
        now_utc=now_utc,
        max_age_seconds=max_age_seconds,
        require_contiguous_sequence=require_contiguous_sequence,
    )
    derived = dict(payload)
    derived["continuity_qualified"] = audit.status.value
    if observations:
        latest = observations[-1]
        derived["sequence"] = latest.sequence
        derived["observed_at_utc"] = latest.observed_at.isoformat()
    return TickflowContinuityEnvelope(payload=derived, audit=audit)
