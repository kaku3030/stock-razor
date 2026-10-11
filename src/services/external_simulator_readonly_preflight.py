"""Transport-free scope consistency check for future external Paper readbacks.

No OpenD SDK, network, datastore, broker, order, alert or scheduler. These
caller-supplied observations alone do NOT prove broker auth or unlock Paper.
A broker-owner must independently verify the source and actual account truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Sequence

from .simulated_account_discovery import AccountMode, SimulatedAccountDiscovery

FAMILIES = frozenset(("BALANCE", "POSITIONS", "OPEN_ORDERS", "FILLS"))
IDENTIFIER = re.compile(r"^[a-zA-Z0-9_.:-]{1,64}$")
MAX_AGE_SECONDS = 60
MAX_ROWS = 10000


class PaperReadOnlyScopeStatus(StrEnum):
    BLOCKED = "BLOCKED"
    SCOPED_INPUTS_CONSISTENT = "SCOPED_INPUTS_CONSISTENT"


@dataclass(frozen=True)
class PaperReadOnlySlice:
    """One *already sanitized* read-only broker query observation.

    Never copy account identifiers, credentials, positions, prices or order
    details to logs or public GitHub Actions outputs.
    """

    family: str
    account_id: str
    mode: str
    market: str
    session_generation: str
    observed_at_utc: datetime
    query_ok: bool
    row_count: int


@dataclass(frozen=True)
class PaperReadOnlyPreflight:
    status: PaperReadOnlyScopeStatus
    reasons: tuple[str, ...]
    observations_checked: int
    research_only: bool = True
    broker_identity_independently_verified: bool = False
    paper_auto_ready: bool = False
    broker_mutation_allowed: bool = False
    live_trade: bool = False


def assess_external_sim_readonly_preflight(
    account: SimulatedAccountDiscovery,
    slices: Sequence[PaperReadOnlySlice],
    *,
    expected_session_generation: str,
    now_utc: datetime,
) -> PaperReadOnlyPreflight:
    """Check source/account/time consistency of 4 non-mutating observations.

    Used only to prepare a supervised read-only acceptance. This cannot
    qualify actual Paper execution because simulated account ownership,
    broker authorization and independently authenticated source remain out
    of scope.
    """

    reasons: set[str] = set()
    if (
        not isinstance(now_utc, datetime)
        or now_utc.tzinfo is None
        or now_utc.utcoffset() is None
    ):
        reasons.add("NOW_NOT_TIMEZONE_AWARE")
        reference_time = None
    else:
        reference_time = now_utc.astimezone(timezone.utc)

    if (
        not isinstance(account, SimulatedAccountDiscovery)
        or account.mode is not AccountMode.SIMULATE
        or account.market != "US"
        or account.authenticated is not True
        or not isinstance(account.account_id, str)
        or not account.account_id.isascii()
        or not account.account_id.isdigit()
        or not account.account_id
    ):
        reasons.add("SIM_ACCOUNT_DISCOVERY_UNVERIFIED")
    else:
        if (
            not isinstance(account.observed_at, datetime)
            or account.observed_at.tzinfo is None
            or account.observed_at.utcoffset() is None
        ):
            reasons.add("DISCOVERY_TIMESTAMP_INVALID")
        elif reference_time is not None:
            age = (reference_time - account.observed_at.astimezone(timezone.utc)).total_seconds()
            if not 0 <= age <= MAX_AGE_SECONDS:
                reasons.add("DISCOVERY_FUTURE_OR_STALE")

    if (
        not isinstance(expected_session_generation, str)
        or IDENTIFIER.fullmatch(expected_session_generation) is None
    ):
        reasons.add("SESSION_GENERATION_UNVERIFIED")

    if not isinstance(slices, (tuple, list)):
        reasons.add("READBACKS_NOT_A_SEQUENCE")
        observations = ()
    else:
        observations = slices
        if len(observations) != len(FAMILIES):
            reasons.add("INCOMPLETE_READBACKS")

    observed: set[str] = set()
    for part in observations:
        if not isinstance(part, PaperReadOnlySlice):
            reasons.add("MALFORMED_READBACK")
            continue
        if not isinstance(part.family, str) or part.family not in FAMILIES:
            reasons.add("UNSUPPORTED_READBACK_FAMILY")
            continue
        if part.family in observed:
            reasons.add("DUPLICATE_READBACK_FAMILY")
        observed.add(part.family)
        if (
            not isinstance(account, SimulatedAccountDiscovery)
            or not isinstance(part.account_id, str)
            or part.account_id != account.account_id
            or part.mode != "SIMULATE"
            or part.market != "US"
        ):
            reasons.add("READBACK_ACCOUNT_SCOPE_MISMATCH")
        if (
            not isinstance(part.session_generation, str)
            or part.session_generation != expected_session_generation
        ):
            reasons.add("READBACK_SESSION_MISMATCH")
        if part.query_ok is not True:
            reasons.add("READBACK_QUERY_FAILED")
        if type(part.row_count) is not int or not 0 <= part.row_count <= MAX_ROWS:
            reasons.add("READBACK_ROW_COUNT_INVALID")
        else:
            if part.family == "BALANCE" and part.row_count != 1:
                reasons.add("BALANCE_EVIDENCE_NOT_SINGLE_ROW")
            if part.family == "POSITIONS" and part.row_count != 0:
                reasons.add("EXISTING_POSITIONS_REQUIRE_OPERATOR_REVIEW")
            if part.family == "OPEN_ORDERS" and part.row_count != 0:
                reasons.add("EXISTING_OPEN_ORDERS_REQUIRE_OPERATOR_REVIEW")
        if (
            not isinstance(part.observed_at_utc, datetime)
            or part.observed_at_utc.tzinfo is None
            or part.observed_at_utc.utcoffset() is None
        ):
            reasons.add("READBACK_TIMESTAMP_INVALID")
        elif reference_time is not None:
            age = (reference_time - part.observed_at_utc.astimezone(timezone.utc)).total_seconds()
            if not 0 <= age <= MAX_AGE_SECONDS:
                reasons.add("READBACK_FUTURE_OR_STALE")

    if observed != FAMILIES:
        reasons.add("MISSING_READBACK_FAMILY")
    return PaperReadOnlyPreflight(
        status=(
            PaperReadOnlyScopeStatus.SCOPED_INPUTS_CONSISTENT
            if not reasons else PaperReadOnlyScopeStatus.BLOCKED
        ),
        reasons=tuple(sorted(reasons)),
        observations_checked=len(observations),
    )
