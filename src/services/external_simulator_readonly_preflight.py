"""Transport-free scope consistency check for future external Paper readbacks.

No OpenD SDK, network, datastore, broker, order, alert or scheduler. These
caller-supplied observations alone do NOT prove broker auth or unlock Paper.
A broker-owner must independently verify the source and actual account truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import re
from typing import Sequence

from .simulated_account_discovery import AccountMode, SimulatedAccountDiscovery

FAMILIES = frozenset(("BALANCE", "POSITIONS", "OPEN_ORDERS", "FILLS"))
IDENTIFIER = re.compile(r"^[a-zA-Z0-9_.:-]{1,64}$")
US_SYMBOL = re.compile(r"US\.[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*\Z")
MAX_AGE_SECONDS = 60
MAX_ROWS = 10000


class PaperReadOnlyScopeStatus(StrEnum):
    BLOCKED = "BLOCKED"
    SCOPED_INPUTS_CONSISTENT = "SCOPED_INPUTS_CONSISTENT"


class PaperEvidenceStatus(StrEnum):
    PASS = "PASS"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class PaperPositionBaseline:
    """One position snapshot with explicit account and read-only provenance."""

    account_id: str
    account_generation: str
    observed_at_utc: datetime
    source: str
    readonly_evidence_id: str
    position_quantity: Decimal
    evidence_kind: str = "READ_ONLY_PROVIDER"
    symbol: str | None = None  # Bind quantity to one observed US instrument.


@dataclass(frozen=True)
class PaperRealizedFillEvidence:
    """Independent read-only evidence for a realized fill.

    This model intentionally has no intent, acknowledgement, or dispatch
    fields.  Those lifecycle facts can be correlated later, but none can
    establish a realized fill on its own.
    """

    fill_id: str
    account_id: str
    account_generation: str
    observed_at_utc: datetime
    source: str
    readonly_evidence_id: str
    side: str
    filled_quantity: Decimal
    average_fill_price: Decimal
    cash_before: Decimal
    cash_after: Decimal
    total_fees: Decimal
    evidence_kind: str = "READ_ONLY_PROVIDER"
    symbol: str | None = None  # Independently sourced instrument identity.


@dataclass(frozen=True)
class PaperEvidenceAssessment:
    status: PaperEvidenceStatus
    reasons: tuple[str, ...]


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
    supported: bool = True


@dataclass(frozen=True)
class PaperFillReconciliation:
    """Sanitized aggregate evidence for a read-only fill cross-check.

    The before/after values must come from the same account/session as the
    fill query.  This is evidence for supervised review only; it never grants
    an order capability.
    """

    side: str
    filled_quantity: Decimal
    average_fill_price: Decimal
    position_quantity_before: Decimal
    position_quantity_after: Decimal
    cash_before: Decimal
    cash_after: Decimal
    # Independently evidenced aggregate fees/taxes in the SAME currency as
    # cash_before/after. Missing evidence is BLOCKED, not assumed zero.
    total_fees: Decimal | None = None


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
    fill_reconciliation: PaperFillReconciliation | None = None,
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
        if part.supported is not True:
            reasons.add("READBACK_UNSUPPORTED")
            if part.family == "FILLS":
                reasons.add("FILLS_EVIDENCE_UNAVAILABLE")
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
    fills = next(
        (
            part
            for part in observations
            if isinstance(part, PaperReadOnlySlice) and part.family == "FILLS"
        ),
        None,
    )
    if fills is not None and fills.supported is True and fills.query_ok is True:
        if type(fills.row_count) is int and fills.row_count == 0:
            if fill_reconciliation is not None:
                reasons.add("UNEXPECTED_FILL_RECONCILIATION")
        elif type(fills.row_count) is int and fills.row_count > 0:
            if fill_reconciliation is None:
                reasons.add("FILLS_RECONCILIATION_REQUIRED")
            else:
                reasons.update(_fill_reconciliation_reasons(fill_reconciliation))
    return PaperReadOnlyPreflight(
        status=(
            PaperReadOnlyScopeStatus.SCOPED_INPUTS_CONSISTENT
            if not reasons else PaperReadOnlyScopeStatus.BLOCKED
        ),
        reasons=tuple(sorted(reasons)),
        observations_checked=len(observations),
    )


def _assessment(status: PaperEvidenceStatus, reasons: set[str]) -> PaperEvidenceAssessment:
    return PaperEvidenceAssessment(status=status, reasons=tuple(sorted(reasons)))


def _required_evidence_text(value: object) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def _valid_us_symbol(value: object) -> bool:
    return isinstance(value, str) and len(value) <= 32 and US_SYMBOL.fullmatch(value) is not None


def _baseline_shape_reasons(baseline: object, *, now_utc: datetime) -> set[str]:
    reasons: set[str] = set()
    if not isinstance(baseline, PaperPositionBaseline):
        return {"POSITION_BASELINE_UNKNOWN"}
    if not _required_evidence_text(baseline.account_id):
        reasons.add("POSITION_BASELINE_ACCOUNT_UNKNOWN")
    if not _required_evidence_text(baseline.account_generation):
        reasons.add("POSITION_BASELINE_GENERATION_UNKNOWN")
    if not _required_evidence_text(baseline.source):
        reasons.add("POSITION_BASELINE_SOURCE_UNKNOWN")
    if not _required_evidence_text(baseline.readonly_evidence_id):
        reasons.add("POSITION_BASELINE_READONLY_EVIDENCE_UNKNOWN")
    if not _valid_us_symbol(baseline.symbol):
        reasons.add("POSITION_BASELINE_SYMBOL_UNKNOWN")
    if baseline.evidence_kind != "READ_ONLY_PROVIDER":
        reasons.add("POSITION_BASELINE_NOT_READONLY_PROVIDER")
    if (
        not isinstance(baseline.observed_at_utc, datetime)
        or baseline.observed_at_utc.tzinfo is None
        or baseline.observed_at_utc.utcoffset() is None
    ):
        reasons.add("POSITION_BASELINE_TIMESTAMP_UNKNOWN")
    elif (
        not isinstance(now_utc, datetime)
        or now_utc.tzinfo is None
        or now_utc.utcoffset() is None
    ):
        reasons.add("POSITION_BASELINE_NOW_UNKNOWN")
    else:
        age = (
            now_utc.astimezone(timezone.utc)
            - baseline.observed_at_utc.astimezone(timezone.utc)
        ).total_seconds()
        if not 0 <= age <= MAX_AGE_SECONDS:
            reasons.add("POSITION_BASELINE_FUTURE_OR_STALE")
    try:
        quantity = Decimal(str(baseline.position_quantity))
    except (InvalidOperation, TypeError, ValueError):
        reasons.add("POSITION_BASELINE_QUANTITY_UNKNOWN")
    else:
        if not quantity.is_finite() or quantity < 0:
            reasons.add("POSITION_BASELINE_QUANTITY_UNKNOWN")
    return reasons


def assess_position_baseline(
    baseline: PaperPositionBaseline | None,
    account: SimulatedAccountDiscovery,
    *,
    expected_account_generation: str,
    expected_source: str,
    expected_readonly_evidence_id: str,
    now_utc: datetime,
) -> PaperEvidenceAssessment:
    """Validate a position baseline without performing provider or broker I/O."""

    reasons = _baseline_shape_reasons(baseline, now_utc=now_utc)
    if reasons:
        return _assessment(
            PaperEvidenceStatus.BLOCKED
            if "POSITION_BASELINE_NOT_READONLY_PROVIDER" in reasons
            else PaperEvidenceStatus.UNKNOWN,
            reasons,
        )
    assert isinstance(baseline, PaperPositionBaseline)
    if (
        not isinstance(account, SimulatedAccountDiscovery)
        or account.mode is not AccountMode.SIMULATE
        or account.market != "US"
        or account.authenticated is not True
    ):
        return _assessment(PaperEvidenceStatus.UNKNOWN, {"SIM_ACCOUNT_DISCOVERY_UNVERIFIED"})
    if baseline.account_id != account.account_id:
        reasons.add("POSITION_BASELINE_ACCOUNT_MISMATCH")
    if baseline.account_generation != expected_account_generation:
        reasons.add("POSITION_BASELINE_GENERATION_MISMATCH")
    if baseline.source != expected_source:
        reasons.add("POSITION_BASELINE_SOURCE_MISMATCH")
    if baseline.readonly_evidence_id != expected_readonly_evidence_id:
        reasons.add("POSITION_BASELINE_READONLY_EVIDENCE_MISMATCH")
    if not _required_evidence_text(expected_account_generation):
        reasons.add("POSITION_BASELINE_GENERATION_UNKNOWN")
    if not _required_evidence_text(expected_source):
        reasons.add("POSITION_BASELINE_SOURCE_UNKNOWN")
    if not _required_evidence_text(expected_readonly_evidence_id):
        reasons.add("POSITION_BASELINE_READONLY_EVIDENCE_UNKNOWN")
    return _assessment(
        PaperEvidenceStatus.BLOCKED if reasons else PaperEvidenceStatus.PASS,
        reasons,
    )


def assess_independent_realized_fill(
    before: PaperPositionBaseline | None,
    after: PaperPositionBaseline | None,
    fill: PaperRealizedFillEvidence | None,
    *,
    now_utc: datetime,
) -> PaperEvidenceAssessment:
    """Require two bound baselines and a separate read-only fill observation."""

    reasons = set()
    before_reasons = _baseline_shape_reasons(before, now_utc=now_utc)
    after_reasons = _baseline_shape_reasons(after, now_utc=now_utc)
    if before_reasons or after_reasons or not isinstance(fill, PaperRealizedFillEvidence):
        reasons.update(before_reasons or {"POSITION_BASELINE_UNKNOWN"})
        reasons.update(after_reasons or {"POSITION_BASELINE_UNKNOWN"})
        if not isinstance(fill, PaperRealizedFillEvidence):
            reasons.add("REALIZED_FILL_UNKNOWN")
        return _assessment(PaperEvidenceStatus.UNKNOWN, reasons)
    assert isinstance(before, PaperPositionBaseline)
    assert isinstance(after, PaperPositionBaseline)
    if not _required_evidence_text(fill.fill_id):
        reasons.add("REALIZED_FILL_ID_UNKNOWN")
    if not _required_evidence_text(fill.account_id):
        reasons.add("REALIZED_FILL_ACCOUNT_UNKNOWN")
    if not _required_evidence_text(fill.account_generation):
        reasons.add("REALIZED_FILL_GENERATION_UNKNOWN")
    if not _required_evidence_text(fill.source):
        reasons.add("REALIZED_FILL_SOURCE_UNKNOWN")
    if not _required_evidence_text(fill.readonly_evidence_id):
        reasons.add("REALIZED_FILL_READONLY_EVIDENCE_UNKNOWN")
    if not _valid_us_symbol(fill.symbol):
        reasons.add("REALIZED_FILL_SYMBOL_UNKNOWN")
    if before.symbol != after.symbol:
        reasons.add("POSITION_BASELINE_SYMBOL_MISMATCH")
    if fill.symbol != before.symbol or fill.symbol != after.symbol:
        reasons.add("REALIZED_FILL_SYMBOL_MISMATCH")
    if fill.evidence_kind != "READ_ONLY_PROVIDER":
        reasons.add("REALIZED_FILL_NOT_READONLY_PROVIDER")
    if (
        not isinstance(fill.observed_at_utc, datetime)
        or fill.observed_at_utc.tzinfo is None
        or fill.observed_at_utc.utcoffset() is None
    ):
        reasons.add("REALIZED_FILL_TIMESTAMP_UNKNOWN")
    elif (
        not isinstance(now_utc, datetime)
        or now_utc.tzinfo is None
        or now_utc.utcoffset() is None
        or not 0 <= (
            now_utc.astimezone(timezone.utc)
            - fill.observed_at_utc.astimezone(timezone.utc)
        ).total_seconds() <= MAX_AGE_SECONDS
    ):
        reasons.add("REALIZED_FILL_FUTURE_OR_STALE")
    if (
        fill.account_id != before.account_id
        or fill.account_id != after.account_id
    ):
        reasons.add("REALIZED_FILL_ACCOUNT_MISMATCH")
    if (
        fill.account_generation != before.account_generation
        or fill.account_generation != after.account_generation
    ):
        reasons.add("REALIZED_FILL_GENERATION_MISMATCH")
    if before.source != after.source or fill.source != before.source:
        reasons.add("REALIZED_FILL_SOURCE_MISMATCH")
    if before.readonly_evidence_id == after.readonly_evidence_id:
        reasons.add("POSITION_BASELINES_NOT_INDEPENDENT")
    if fill.readonly_evidence_id in {
        before.readonly_evidence_id,
        after.readonly_evidence_id,
    }:
        reasons.add("REALIZED_FILL_READONLY_EVIDENCE_NOT_INDEPENDENT")
    timestamps = (before.observed_at_utc, fill.observed_at_utc, after.observed_at_utc)
    if any(
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        for value in timestamps
    ):
        reasons.add("REALIZED_FILL_TIMESTAMP_UNKNOWN")
    elif not before.observed_at_utc <= fill.observed_at_utc <= after.observed_at_utc:
        reasons.add("REALIZED_FILL_TIMESTAMP_ORDER_MISMATCH")
    if reasons:
        return _assessment(PaperEvidenceStatus.BLOCKED, reasons)
    numeric = PaperFillReconciliation(
        side=fill.side,
        filled_quantity=fill.filled_quantity,
        average_fill_price=fill.average_fill_price,
        position_quantity_before=before.position_quantity,
        position_quantity_after=after.position_quantity,
        cash_before=fill.cash_before,
        cash_after=fill.cash_after,
        total_fees=fill.total_fees,
    )
    reasons.update(_fill_reconciliation_reasons(numeric))
    return _assessment(
        PaperEvidenceStatus.BLOCKED if reasons else PaperEvidenceStatus.PASS,
        reasons,
    )


def _fill_reconciliation_reasons(
    reconciliation: PaperFillReconciliation,
) -> set[str]:
    reasons: set[str] = set()
    if not isinstance(reconciliation, PaperFillReconciliation):
        return {"MALFORMED_FILL_RECONCILIATION"}
    side = reconciliation.side.upper() if isinstance(reconciliation.side, str) else ""
    if side not in {"BUY", "SELL"}:
        reasons.add("FILL_SIDE_UNVERIFIED")

    if reconciliation.total_fees is None:
        return reasons | {"FILL_FEE_EVIDENCE_MISSING"}
    values = (
        reconciliation.filled_quantity,
        reconciliation.average_fill_price,
        reconciliation.position_quantity_before,
        reconciliation.position_quantity_after,
        reconciliation.cash_before,
        reconciliation.cash_after,
        reconciliation.total_fees,
    )
    try:
        decimals = tuple(Decimal(str(value)) for value in values)
    except (InvalidOperation, TypeError, ValueError):
        return reasons | {"FILL_RECONCILIATION_VALUE_INVALID"}
    if not all(value.is_finite() for value in decimals):
        reasons.add("FILL_RECONCILIATION_VALUE_INVALID")
        return reasons
    (
        filled_quantity,
        average_price,
        position_before,
        position_after,
        cash_before,
        cash_after,
        total_fees,
    ) = decimals
    if total_fees < 0:
        reasons.add("FILL_FEES_INVALID")
    if filled_quantity <= 0 or average_price <= 0:
        reasons.add("FILL_QUANTITY_OR_AVERAGE_INVALID")
    if position_before < 0 or position_after < 0:
        reasons.add("POSITION_QUANTITY_INVALID")
    if side in {"BUY", "SELL"} and filled_quantity > 0:
        expected_delta = filled_quantity if side == "BUY" else -filled_quantity
        if position_after - position_before != expected_delta:
            reasons.add("FILL_POSITION_DELTA_MISMATCH")
        notional = filled_quantity * average_price
        if notional.is_finite() and total_fees > notional:
            reasons.add("FILL_FEES_EXCEED_NOTIONAL")
        # Buyer pays notional + fees; seller receives notional - fees.
        # Require exact Decimal equality: undocumented fee, rebate, FX,
        # deposit/withdrawal or other cash movement must fail closed.
        expected_cash_movement = (
            notional + total_fees if side == "BUY" else notional - total_fees
        )
        cash_movement = (
            cash_before - cash_after if side == "BUY"
            else cash_after - cash_before
        )
        if (
            not expected_cash_movement.is_finite()
            or cash_movement != expected_cash_movement
        ):
            reasons.add("FILL_CASH_FLOW_MISMATCH")
    return reasons
