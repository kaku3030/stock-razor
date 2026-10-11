"""Read-only admission barrier for pre-existing broker SIM inventory.

Legacy holdings are not fills created by STOCK RAZOR, and neither an app
screenshot nor a broker position query can authorize external Paper orders.
No network, broker SDK, logging, account persistence or order APIs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Sequence

_US_SYMBOL = re.compile(r"US\.[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*\Z")
MAX_READBACK_AGE_SECONDS = 60


@dataclass(frozen=True)
class LegacySimPosition:
    symbol: str
    side: str
    quantity: Decimal


@dataclass(frozen=True)
class LegacySimInventoryAssessment:
    status: str
    reasons: tuple[str, ...]
    position_count: int
    user_ui_comparison: str
    existing_positions_quarantined: bool = True
    old_pnl_strategy_eligible: bool = False
    independent_realized_fills_proven: bool = False
    paper_auto_ready: bool = False
    broker_mutation_allowed: bool = False
    live_trade: bool = False


def _positions(value: object) -> dict[tuple[str, str], Decimal] | None:
    if not isinstance(value, (tuple, list)):
        return None
    result: dict[tuple[str, str], Decimal] = {}
    for row in value:
        if not isinstance(row, LegacySimPosition):
            return None
        if (
            not isinstance(row.symbol, str)
            or len(row.symbol) > 32
            or _US_SYMBOL.fullmatch(row.symbol) is None
            or row.side not in {"LONG", "SHORT"}
        ):
            return None
        try:
            quantity = Decimal(str(row.quantity))
        except (InvalidOperation, ValueError, TypeError):
            return None
        if not quantity.is_finite() or quantity <= 0:
            return None
        key = row.symbol, row.side
        if key in result:
            return None
        result[key] = quantity
    return result


def assess_legacy_sim_inventory(
    broker_positions: Sequence[LegacySimPosition] | None,
    *,
    observed_account_id: str | None,
    expected_account_id: str | None,
    account_mode: str,
    account_market: str,
    session_authenticated: bool,
    broker_observed_at_utc: datetime | None,
    now_utc: datetime,
    user_ui_positions: Sequence[LegacySimPosition] | None = None,
) -> LegacySimInventoryAssessment:
    """Classify historical SIM inventory without promoting screenshot or P&L evidence."""
    blocked: set[str] = set()
    unknown: set[str] = set()
    if (
        not isinstance(expected_account_id, str)
        or not expected_account_id.isascii()
        or not expected_account_id.isdigit()
        or not expected_account_id
        or not isinstance(observed_account_id, str)
        or observed_account_id != expected_account_id
    ):
        blocked.add("SIM_ACCOUNT_IDENTITY_NOT_PROVEN")
    if account_mode != "SIMULATE" or account_market != "US":
        blocked.add("NON_US_SIM_ACCOUNT")
    if session_authenticated is not True:
        blocked.add("BROKER_SESSION_UNAUTHENTICATED")
    if (
        not isinstance(now_utc, datetime)
        or now_utc.tzinfo is None or now_utc.utcoffset() is None
        or not isinstance(broker_observed_at_utc, datetime)
        or broker_observed_at_utc.tzinfo is None
        or broker_observed_at_utc.utcoffset() is None
    ):
        unknown.add("BROKER_READBACK_TIME_UNKNOWN")
    else:
        age = (
            now_utc.astimezone(timezone.utc)
            - broker_observed_at_utc.astimezone(timezone.utc)
        ).total_seconds()
        if not 0 <= age <= MAX_READBACK_AGE_SECONDS:
            unknown.add("BROKER_READBACK_FUTURE_OR_STALE")

    positions = _positions(broker_positions)
    if positions is None:
        blocked.add("MALFORMED_OR_DUPLICATE_BROKER_POSITIONS")
    elif not positions:
        unknown.add("NO_LEGACY_POSITIONS_TO_RECONCILE")
    else:
        unknown.add("LEGACY_POSITION_ORIGIN_UNVERIFIED")

    ui_status = "NOT_SUPPLIED"
    if user_ui_positions is not None:
        ui = _positions(user_ui_positions)
        if ui is None:
            blocked.add("MALFORMED_USER_UI_POSITIONS")
            ui_status = "INVALID"
        elif positions is not None and ui != positions:
            blocked.add("USER_UI_BROKER_POSITION_MISMATCH")
            ui_status = "MISMATCH"
        elif positions is not None:
            ui_status = "MATCH_NOT_PROOF_OF_FILLS"
    if blocked:
        status = "BLOCKED"
    elif unknown:
        status = "QUARANTINED" if positions else "UNKNOWN"
    else:
        status = "QUARANTINED"
    return LegacySimInventoryAssessment(
        status=status,
        reasons=tuple(sorted(blocked | unknown)),
        position_count=len(positions or ()),
        user_ui_comparison=ui_status,
    )
