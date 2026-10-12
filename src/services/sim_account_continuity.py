"""Privacy-safe cross-host US SIM identity and legacy position continuity.

No account ID, balances or positions are returned by the assessment.
The caller holds confidential broker readbacks in memory only, and this
module never imports a broker SDK, reaches a host, or places an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from .legacy_sim_inventory import LegacySimPosition, _positions


@dataclass(frozen=True)
class SimAccountHostObservation:
    account_id: str
    source: str
    account_generation: str
    observed_at_utc: datetime
    account_mode: str
    market: str
    authenticated: bool
    positions: Sequence[LegacySimPosition]


@dataclass(frozen=True)
class SimContinuityReview:
    status: str
    reason: str
    position_count: int = 0
    same_account_id: bool = False
    same_positions: bool = False
    evidence_scope: str = "CROSS_HOST_READBACK_NOT_BROKER_FILL_EVIDENCE"
    paper_auto_ready: bool = False
    broker_mutation_allowed: bool = False
    radar_admission: str = "BLOCKED"
    live_trade: bool = False


def compare_local_cloud_sim(
    windows: object,
    aws: object,
    *,
    now_utc: datetime,
    expected_account_id: str | None = None,
    max_age_seconds: int = 120,
    max_skew_seconds: int = 120,
) -> SimContinuityReview:
    """Cross-check identity and positions; never promote to execution."""
    def stop(reason: str) -> SimContinuityReview:
        return SimContinuityReview("BLOCKED", reason)

    if not isinstance(windows, SimAccountHostObservation) or not isinstance(
        aws, SimAccountHostObservation
    ):
        return stop("TWO_INDEPENDENT_OBSERVATIONS_REQUIRED")
    if windows.source != "WINDOWS_LOCAL_OPEND" or aws.source != "AWS_OPEND_SSM":
        return stop("OBSERVATION_SOURCE_MISMATCH")
    for record in (windows, aws):
        if (
            record.account_mode != "SIMULATE" or record.market != "US"
            or record.authenticated is not True
        ):
            return stop("NON_AUTHENTICATED_OR_NON_US_SIM_ACCOUNT")
        if (
            not isinstance(record.account_id, str)
            or not record.account_id.isascii()
            or not record.account_id.isdigit()
            or not record.account_id
            or not isinstance(record.account_generation, str)
            or not record.account_generation.strip()
        ):
            return stop("ACCOUNT_IDENTITY_EVIDENCE_INVALID")
        if not isinstance(record.observed_at_utc, datetime):
            return stop("OBSERVATION_TIME_UNKNOWN")
        if record.observed_at_utc.tzinfo is None or record.observed_at_utc.utcoffset() is None:
            return stop("OBSERVATION_TIME_UNKNOWN")
    if not isinstance(now_utc, datetime) or now_utc.tzinfo is None or now_utc.utcoffset() is None:
        return stop("REVIEW_CLOCK_UNKNOWN")
    if (
        type(max_age_seconds) is not int or max_age_seconds <= 0
        or type(max_skew_seconds) is not int or max_skew_seconds <= 0
    ):
        return stop("INVALID_AGE_POLICY")
    ages = tuple(
        (now_utc.astimezone(timezone.utc)-x.observed_at_utc.astimezone(timezone.utc)).total_seconds()
        for x in (windows, aws)
    )
    if any(not 0 <= age <= max_age_seconds for age in ages):
        return stop("BROKER_READBACK_STALE_OR_FUTURE")
    if abs(ages[0]-ages[1]) > max_skew_seconds:
        return stop("CROSS_HOST_OBSERVATION_SKEW")
    if windows.account_id != aws.account_id:
        return stop("CROSS_HOST_SIM_ACCOUNT_ID_MISMATCH")
    # Matching across two hosts is not sufficient: it must also be the
    # SIM account privately authorized by the operator. Never emit its ID.
    if (not isinstance(expected_account_id, str)
            or not expected_account_id.isascii()
            or not expected_account_id.isdigit()
            or not 1 <= len(expected_account_id) <= 20):
        return stop("APPROVED_SIM_ACCOUNT_ID_REQUIRED")
    if windows.account_id != expected_account_id:
        return stop("APPROVED_SIM_ACCOUNT_ID_MISMATCH")
    prior, later = _positions(windows.positions), _positions(aws.positions)
    if prior is None or later is None:
        return stop("MALFORMED_READBACK_POSITIONS")
    if prior != later:
        return SimContinuityReview(
            "BLOCKED", "CROSS_HOST_POSITION_MISMATCH",
            position_count=len(prior), same_account_id=True,
        )
    if not prior:
        return stop("NO_LEGACY_POSITIONS_OBSERVED")
    return SimContinuityReview(
        "MATCHED_FOR_REVIEW", "INDEPENDENT_FILLS_STILL_UNKNOWN",
        len(prior), same_account_id=True, same_positions=True,
    )
