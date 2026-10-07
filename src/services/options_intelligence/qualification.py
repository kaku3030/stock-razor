"""Qualification gates for options-intelligence observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .gex import OptionGexObservation


_ALLOWED_PHASES = {
    "premarket",
    "intraday",
    "closing_auction",
    "postmarket",
    "non_trading",
    "unknown",
}


@dataclass(frozen=True)
class OptionsFreshnessPolicy:
    """Auditable quote-freshness floor for the current US options phase."""

    evaluated_at: datetime
    phase: str
    min_quote_asof: datetime | None
    status: str
    reference_session_close: datetime | None = None
    warnings: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "evaluated_at": self.evaluated_at.isoformat(),
            "phase": self.phase,
            "min_quote_asof": (
                self.min_quote_asof.isoformat()
                if self.min_quote_asof is not None
                else None
            ),
            "status": self.status,
            "reference_session_close": (
                self.reference_session_close.isoformat()
                if self.reference_session_close is not None
                else None
            ),
            "warnings": list(self.warnings),
        }


def resolve_us_options_freshness_policy(
    *,
    evaluated_at: datetime,
    phase: str,
    reference_session_close: datetime | None = None,
    regular_session_max_age: timedelta = timedelta(minutes=15),
    completed_session_tail: timedelta = timedelta(minutes=30),
) -> OptionsFreshnessPolicy:
    """Resolve a session-aware freshness floor without guessing holidays.

    Regular-session observations use a floor relative to evaluated_at.
    Premarket/postmarket/non-trading callers must supply the completed
    reference session close from an exchange calendar. This deliberately
    avoids inferring previous sessions with weekday arithmetic.
    """

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    if regular_session_max_age <= timedelta(0):
        raise ValueError("regular_session_max_age must be positive")
    if completed_session_tail <= timedelta(0):
        raise ValueError("completed_session_tail must be positive")

    normalized_phase = str(phase or "").strip().lower()
    if normalized_phase not in _ALLOWED_PHASES:
        normalized_phase = "unknown"

    if normalized_phase in {"intraday", "closing_auction"}:
        return OptionsFreshnessPolicy(
            evaluated_at=evaluated_at,
            phase=normalized_phase,
            min_quote_asof=evaluated_at - regular_session_max_age,
            status="READY",
        )

    if normalized_phase in {"premarket", "postmarket", "non_trading"}:
        if reference_session_close is None:
            return OptionsFreshnessPolicy(
                evaluated_at=evaluated_at,
                phase=normalized_phase,
                min_quote_asof=None,
                status="BLOCKED_UNKNOWN_SESSION_REFERENCE",
                warnings=("REFERENCE_SESSION_CLOSE_REQUIRED",),
            )
        if (
            reference_session_close.tzinfo is None
            or reference_session_close.utcoffset() is None
        ):
            raise ValueError("reference_session_close must be timezone-aware")
        if reference_session_close > evaluated_at:
            return OptionsFreshnessPolicy(
                evaluated_at=evaluated_at,
                phase=normalized_phase,
                min_quote_asof=None,
                status="BLOCKED_FUTURE_SESSION_REFERENCE",
                reference_session_close=reference_session_close,
                warnings=("REFERENCE_SESSION_CLOSE_IS_IN_FUTURE",),
            )
        return OptionsFreshnessPolicy(
            evaluated_at=evaluated_at,
            phase=normalized_phase,
            min_quote_asof=reference_session_close - completed_session_tail,
            status="READY",
            reference_session_close=reference_session_close,
        )

    return OptionsFreshnessPolicy(
        evaluated_at=evaluated_at,
        phase="unknown",
        min_quote_asof=None,
        status="BLOCKED_UNKNOWN_PHASE",
        warnings=("OPTIONS_SESSION_PHASE_UNKNOWN",),
    )


@dataclass(frozen=True)
class GexFreshnessQualification:
    observations: tuple[OptionGexObservation, ...]
    source_total: int
    stale_rejected: int
    missing_timestamp_rejected: int
    min_quote_asof: datetime | None
    policy_phase: str = "explicit_floor"
    policy_status: str = "READY"
    policy_warnings: tuple[str, ...] = ()

    @property
    def usable(self) -> int:
        return len(self.observations)

    @property
    def completeness(self) -> float:
        return self.usable / self.source_total if self.source_total else 0.0

    @property
    def status(self) -> str:
        if self.policy_status != "READY":
            return "BLOCKED"
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
            "min_quote_asof": (
                self.min_quote_asof.isoformat()
                if self.min_quote_asof is not None
                else None
            ),
            "completeness": self.completeness,
            "status": self.status,
            "policy_phase": self.policy_phase,
            "policy_status": self.policy_status,
            "policy_warnings": list(self.policy_warnings),
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


def qualify_quote_freshness_with_policy(
    observations: Iterable[OptionGexObservation],
    *,
    policy: OptionsFreshnessPolicy,
) -> GexFreshnessQualification:
    """Apply a resolved session-aware freshness policy."""

    rows = list(observations)
    if policy.status != "READY" or policy.min_quote_asof is None:
        return GexFreshnessQualification(
            observations=(),
            source_total=len(rows),
            stale_rejected=0,
            missing_timestamp_rejected=0,
            min_quote_asof=policy.min_quote_asof,
            policy_phase=policy.phase,
            policy_status=policy.status,
            policy_warnings=policy.warnings,
        )

    base = qualify_quote_freshness(
        rows,
        min_quote_asof=policy.min_quote_asof,
    )
    return GexFreshnessQualification(
        observations=base.observations,
        source_total=base.source_total,
        stale_rejected=base.stale_rejected,
        missing_timestamp_rejected=base.missing_timestamp_rejected,
        min_quote_asof=base.min_quote_asof,
        policy_phase=policy.phase,
        policy_status=policy.status,
        policy_warnings=policy.warnings,
    )


@dataclass(frozen=True)
class OptionsClockQualification:
    """Three-clock gate for spot, option quote/Greeks, and OI timestamps."""

    underlying_asof: datetime | None
    quote_asof_min: datetime | None
    quote_asof_max: datetime | None
    oi_asof_min: datetime | None
    oi_asof_max: datetime | None
    max_underlying_quote_skew_seconds: float
    actual_underlying_quote_skew_seconds: float | None
    status: str
    warnings: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "underlying_asof": (
                self.underlying_asof.isoformat()
                if self.underlying_asof is not None
                else None
            ),
            "quote_asof_min": (
                self.quote_asof_min.isoformat()
                if self.quote_asof_min is not None
                else None
            ),
            "quote_asof_max": (
                self.quote_asof_max.isoformat()
                if self.quote_asof_max is not None
                else None
            ),
            "oi_asof_min": (
                self.oi_asof_min.isoformat()
                if self.oi_asof_min is not None
                else None
            ),
            "oi_asof_max": (
                self.oi_asof_max.isoformat()
                if self.oi_asof_max is not None
                else None
            ),
            "max_underlying_quote_skew_seconds": (
                self.max_underlying_quote_skew_seconds
            ),
            "actual_underlying_quote_skew_seconds": (
                self.actual_underlying_quote_skew_seconds
            ),
            "status": self.status,
            "warnings": list(self.warnings),
        }


def qualify_options_clock_alignment(
    freshness: GexFreshnessQualification,
    *,
    underlying_asof: datetime | None,
    max_underlying_quote_skew: timedelta = timedelta(minutes=20),
    require_oi_asof: bool = False,
) -> OptionsClockQualification:
    """Prevent mixed-clock GEX such as live premarket spot + prior-close Greeks."""

    if max_underlying_quote_skew <= timedelta(0):
        raise ValueError("max_underlying_quote_skew must be positive")
    if underlying_asof is not None and (
        underlying_asof.tzinfo is None or underlying_asof.utcoffset() is None
    ):
        raise ValueError("underlying_asof must be timezone-aware")

    quote_values = [
        row.quote_asof
        for row in freshness.observations
        if row.quote_asof is not None
    ]
    oi_values = [
        row.oi_asof
        for row in freshness.observations
        if row.oi_asof is not None
    ]
    quote_min = min(quote_values) if quote_values else None
    quote_max = max(quote_values) if quote_values else None
    oi_min = min(oi_values) if oi_values else None
    oi_max = max(oi_values) if oi_values else None
    max_seconds = max_underlying_quote_skew.total_seconds()

    if freshness.status == "BLOCKED":
        return OptionsClockQualification(
            underlying_asof=underlying_asof,
            quote_asof_min=quote_min,
            quote_asof_max=quote_max,
            oi_asof_min=oi_min,
            oi_asof_max=oi_max,
            max_underlying_quote_skew_seconds=max_seconds,
            actual_underlying_quote_skew_seconds=None,
            status="BLOCKED",
            warnings=("QUOTE_FRESHNESS_BLOCKED",),
        )

    if underlying_asof is None:
        return OptionsClockQualification(
            underlying_asof=None,
            quote_asof_min=quote_min,
            quote_asof_max=quote_max,
            oi_asof_min=oi_min,
            oi_asof_max=oi_max,
            max_underlying_quote_skew_seconds=max_seconds,
            actual_underlying_quote_skew_seconds=None,
            status="BLOCKED",
            warnings=("UNDERLYING_ASOF_UNKNOWN",),
        )

    if quote_max is None:
        return OptionsClockQualification(
            underlying_asof=underlying_asof,
            quote_asof_min=quote_min,
            quote_asof_max=None,
            oi_asof_min=oi_min,
            oi_asof_max=oi_max,
            max_underlying_quote_skew_seconds=max_seconds,
            actual_underlying_quote_skew_seconds=None,
            status="BLOCKED",
            warnings=("OPTION_QUOTE_ASOF_UNKNOWN",),
        )

    skew_seconds = abs((underlying_asof - quote_max).total_seconds())
    if skew_seconds > max_seconds:
        return OptionsClockQualification(
            underlying_asof=underlying_asof,
            quote_asof_min=quote_min,
            quote_asof_max=quote_max,
            oi_asof_min=oi_min,
            oi_asof_max=oi_max,
            max_underlying_quote_skew_seconds=max_seconds,
            actual_underlying_quote_skew_seconds=skew_seconds,
            status="BLOCKED",
            warnings=("UNDERLYING_OPTION_CLOCK_SKEW_TOO_LARGE",),
        )

    if oi_min is None or oi_max is None:
        status = "BLOCKED" if require_oi_asof else "DEGRADED"
        warnings = ("OI_ASOF_UNKNOWN",)
    else:
        status = "PASS_RESEARCH"
        warnings = ()

    return OptionsClockQualification(
        underlying_asof=underlying_asof,
        quote_asof_min=quote_min,
        quote_asof_max=quote_max,
        oi_asof_min=oi_min,
        oi_asof_max=oi_max,
        max_underlying_quote_skew_seconds=max_seconds,
        actual_underlying_quote_skew_seconds=skew_seconds,
        status=status,
        warnings=warnings,
    )
