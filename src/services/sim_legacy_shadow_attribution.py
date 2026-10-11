"""Legacy-aware US SIM Paper strategy attribution, offline and non-executable.

This is a reviewer for caller-supplied observations, NOT an authenticated
fill source, order journal, P&L calculation, or broker trading client.
Historical/manual inventory is isolated from any hypothetical strategy
delta. The only possible favorable outcome is SHADOW_REVIEW_ONLY.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Sequence

from .legacy_sim_inventory import LegacySimPosition, _positions

_ID = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")
_SYMBOL = re.compile(r"US\.[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*\Z")
_MAX_ROWS = 1000


@dataclass(frozen=True)
class ShadowStrategyFill:
    """Self-reported simulated fill requiring future independent attestation."""

    fill_id: str
    strategy_action_id: str
    account_id: str
    symbol: str
    side: str
    quantity: Decimal
    observed_at_utc: datetime


@dataclass(frozen=True)
class ShadowAttributionReview:
    status: str
    reason: str
    legacy_instrument_count: int = 0
    strategy_instrument_count: int = 0
    reviewed_fill_count: int = 0
    provenance_status: str = "NOT_INDEPENDENTLY_ATTESTED"
    strategy_pnl_eligible: bool = False
    independent_realized_fills_proven: bool = False
    paper_auto_ready: bool = False
    broker_mutation_allowed: bool = False
    radar_admission: str = "BLOCKED"
    source_arbiter_admission: str = "BLOCKED"
    live_trade: bool = False


def _utc(value: object) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    if value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _decimal_positive(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def _long_only_rows(rows: object) -> dict[str, Decimal] | None:
    parsed = _positions(rows)
    if parsed is None or any(side != "LONG" for _, side in parsed):
        return None
    return {symbol: quantity for (symbol, _), quantity in parsed.items()}


def review_legacy_sim_strategy_deltas(
    *,
    account_id: str,
    legacy_baseline: Sequence[LegacySimPosition],
    current_broker_positions: Sequence[LegacySimPosition],
    reported_strategy_fills: Sequence[ShadowStrategyFill],
    baseline_observed_at_utc: datetime,
    strategy_started_at_utc: datetime,
    current_observed_at_utc: datetime,
    operator_accepted_legacy: bool = False,
) -> ShadowAttributionReview:
    """Require exact old inventory + hypothetical deltas to equal current readback.

    Deliberately does NOT assign independent broker provenance to input rows.
    Never returns a trade-intent, external order permission or strategy P&L.
    """

    def stop(status: str, reason: str) -> ShadowAttributionReview:
        return ShadowAttributionReview(status, reason)

    if operator_accepted_legacy is not True:
        return stop("BLOCKED", "LEGACY_INVENTORY_NOT_ACCEPTED")
    if (
        not isinstance(account_id, str)
        or not account_id.isascii()
        or not account_id.isdigit()
        or not account_id
    ):
        return stop("BLOCKED", "ACCOUNT_SCOPE_UNKNOWN")
    baseline_time = _utc(baseline_observed_at_utc)
    started = _utc(strategy_started_at_utc)
    observed = _utc(current_observed_at_utc)
    if None in (baseline_time, started, observed):
        return stop("BLOCKED", "OBSERVATION_TIMESTAMPS_UNKNOWN")
    if not baseline_time <= started <= observed:
        return stop("BLOCKED", "OBSERVATION_TIME_ORDER_INVALID")
    if (
        not isinstance(legacy_baseline, (list, tuple))
        or not isinstance(current_broker_positions, (list, tuple))
        or not isinstance(reported_strategy_fills, (list, tuple))
        or len(legacy_baseline) > _MAX_ROWS
        or len(current_broker_positions) > _MAX_ROWS
        or len(reported_strategy_fills) > _MAX_ROWS
    ):
        return stop("BLOCKED", "ROW_SHAPE_OR_LIMIT_INVALID")

    baseline = _long_only_rows(legacy_baseline)
    current = _long_only_rows(current_broker_positions)
    if baseline is None or current is None or not baseline:
        return stop("BLOCKED", "LEGACY_OR_CURRENT_INVENTORY_INVALID")
    if any(_SYMBOL.fullmatch(symbol) is None for symbol in (*baseline, *current)):
        return stop("BLOCKED", "INSTRUMENT_INVALID")

    strategy: dict[str, Decimal] = {}
    seen_fill_ids: set[str] = set()
    seen_actions: set[str] = set()
    previous = started
    for event in reported_strategy_fills:
        if not isinstance(event, ShadowStrategyFill):
            return stop("BLOCKED", "MALFORMED_FILL")
        if (
            not isinstance(event.fill_id, str)
            or _ID.fullmatch(event.fill_id) is None
            or not isinstance(event.strategy_action_id, str)
            or _ID.fullmatch(event.strategy_action_id) is None
        ):
            return stop("BLOCKED", "FILL_OR_ACTION_ID_INVALID")
        if event.fill_id in seen_fill_ids:
            return stop("BLOCKED", "DUPLICATE_FILL_ID")
        # One hypothetical fill per explicit strategy action; real partial
        # fills need separately specified aggregation and provider evidence.
        if event.strategy_action_id in seen_actions:
            return stop("BLOCKED", "DUPLICATE_STRATEGY_ACTION")
        seen_fill_ids.add(event.fill_id)
        seen_actions.add(event.strategy_action_id)
        if event.account_id != account_id:
            return stop("BLOCKED", "FILL_ACCOUNT_MISMATCH")
        if (
            not isinstance(event.symbol, str)
            or len(event.symbol) > 32
            or _SYMBOL.fullmatch(event.symbol) is None
            or event.side not in ("BUY", "SELL")
        ):
            return stop("BLOCKED", "FILL_INSTRUMENT_OR_SIDE_INVALID")
        quantity = _decimal_positive(event.quantity)
        if quantity is None:
            return stop("BLOCKED", "FILL_QUANTITY_INVALID")
        at = _utc(event.observed_at_utc)
        if at is None or not previous <= at <= observed:
            return stop("BLOCKED", "FILL_OUTSIDE_ORDERED_STRATEGY_WINDOW")
        previous = at
        before = strategy.get(event.symbol, Decimal(0))
        after = before + (quantity if event.side == "BUY" else -quantity)
        if after < 0:
            # Never silently sell or attribute pre-existing manual holdings
            # to a new strategy.
            return stop("BLOCKED", "LEGACY_POSITION_SALE_NOT_STRATEGY_FILL")
        strategy[event.symbol] = after

    expected = dict(baseline)
    for symbol, additional in strategy.items():
        expected[symbol] = expected.get(symbol, Decimal(0)) + additional
    expected = {symbol: amount for symbol, amount in expected.items() if amount}
    if expected != current:
        return stop("BLOCKED", "BROKER_POSITIONS_DO_NOT_MATCH_SHADOW_DELTAS")

    return ShadowAttributionReview(
        status="SHADOW_REVIEW_ONLY" if reported_strategy_fills else "LEGACY_BASELINE_ONLY",
        reason="UNATTESTED_SELF_REPORTED_FILL_EVIDENCE",
        legacy_instrument_count=len(baseline),
        strategy_instrument_count=sum(quantity > 0 for quantity in strategy.values()),
        reviewed_fill_count=len(reported_strategy_fills),
    )
