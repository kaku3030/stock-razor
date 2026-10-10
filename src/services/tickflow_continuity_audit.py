"""Offline continuity audit for redacted TickFlow observations.

This validates supplied evidence only. It does not open a WebSocket, fetch
market data, or authorize a source.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class TickflowContinuityStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class TickflowObservation:
    sequence: int | None
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.sequence is not None and (
            isinstance(self.sequence, bool) or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise ValueError("sequence must be a nonnegative integer or null")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        object.__setattr__(
            self, "observed_at", self.observed_at.astimezone(timezone.utc)
        )


@dataclass(frozen=True)
class TickflowContinuityAudit:
    status: TickflowContinuityStatus
    observations: int
    reasons: tuple[str, ...]


def audit_tickflow_continuity(
    observations: tuple[TickflowObservation, ...],
    *,
    now_utc: datetime,
    max_age_seconds: float,
    require_contiguous_sequence: bool = True,
) -> TickflowContinuityAudit:
    """Audit ordering, sequence continuity, freshness, and future timestamps."""
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must be nonnegative")
    now = now_utc.astimezone(timezone.utc)
    reasons: list[str] = []
    if not observations:
        reasons.append("NO_OBSERVATIONS")
    sequences = tuple(item.sequence for item in observations)
    if any(sequence is None for sequence in sequences):
        reasons.append("SEQUENCE_MISSING")
    known = tuple(sequence for sequence in sequences if sequence is not None)
    if known and known != tuple(sorted(known)):
        reasons.append("SEQUENCE_NOT_MONOTONIC")
    if len(set(known)) != len(known):
        reasons.append("SEQUENCE_DUPLICATE")
    if require_contiguous_sequence and known:
        expected = tuple(range(known[0], known[-1] + 1))
        if known != expected:
            reasons.append("SEQUENCE_GAP")
    times = tuple(item.observed_at for item in observations)
    if times and times != tuple(sorted(times)):
        reasons.append("TIMESTAMP_NOT_MONOTONIC")
    if any(item.observed_at > now for item in observations):
        reasons.append("FUTURE_TIMESTAMP")
    if times and (now - times[-1]).total_seconds() > max_age_seconds:
        reasons.append("LATEST_OBSERVATION_STALE")
    return TickflowContinuityAudit(
        status=(
            TickflowContinuityStatus.PASS
            if not reasons
            else TickflowContinuityStatus.BLOCKED
        ),
        observations=len(observations),
        reasons=tuple(dict.fromkeys(reasons)),
    )
