"""Qualification gates for options-intelligence observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .gex import OptionGexObservation


@dataclass(frozen=True)
class GexFreshnessQualification:
    observations: tuple[OptionGexObservation, ...]
    source_total: int
    stale_rejected: int
    missing_timestamp_rejected: int
    min_quote_asof: datetime

    @property
    def usable(self) -> int:
        return len(self.observations)

    @property
    def completeness(self) -> float:
        return self.usable / self.source_total if self.source_total else 0.0

    @property
    def status(self) -> str:
        if self.source_total == 0 or self.usable == 0:
            return "BLOCKED"
        if self.completeness < 0.80:
            return "DEGRADED"
        return "PASS_RESEARCH"

    def to_payload(self) -> dict[str, object]:
        return {
            "source_total": self.source_total,
            "usable": self.usable,
            "stale_rejected": self.stale_rejected,
            "missing_timestamp_rejected": self.missing_timestamp_rejected,
            "min_quote_asof": self.min_quote_asof.isoformat(),
            "completeness": self.completeness,
            "status": self.status,
        }


def qualify_quote_freshness(
    observations: Iterable[OptionGexObservation],
    *,
    min_quote_asof: datetime,
) -> GexFreshnessQualification:
    """Require each option Greek/quote observation to meet a time floor."""

    if min_quote_asof.tzinfo is None or min_quote_asof.utcoffset() is None:
        raise ValueError("min_quote_asof must be timezone-aware")

    rows = list(observations)
    accepted: list[OptionGexObservation] = []
    stale = 0
    missing = 0

    for row in rows:
        if row.quote_asof is None:
            missing += 1
            continue
        if row.quote_asof < min_quote_asof:
            stale += 1
            continue
        accepted.append(row)

    return GexFreshnessQualification(
        observations=tuple(accepted),
        source_total=len(rows),
        stale_rejected=stale,
        missing_timestamp_rejected=missing,
        min_quote_asof=min_quote_asof,
    )
