"""Zero-I/O TickFlow Expert ETF history acceptance planning.

A signed plan is NOT a provider command, admission, or payment authorization.
No SDK, credentials, requests, ledger side effects, or cloud execution.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_SYMBOL = re.compile(r"(?:[0-9]{6})\.(?:SH|SZ)\Z")
_TIMEFRAMES = frozenset(("1m", "5m", "15m", "30m", "60m"))
# Plan-screenshot maximum 365 days and up to 200 symbols per minute batch.
# Pilot contract intentionally caps at five ETF instruments and one batch.
_MINUTE_HISTORY_DAYS = 365


@dataclass(frozen=True)
class TickFlowHistoryPilot:
    symbols: tuple[str, ...]
    start_utc: datetime
    end_utc: datetime
    timeframe: str
    max_provider_requests: int = 1


@dataclass(frozen=True)
class TickFlowPilotReview:
    status: str
    reason: str
    symbol_count: int = 0
    planned_request_ceiling: int = 0
    provider_calls: int = 0
    ledger_reservations: int = 0
    source_arbiter_admission: str = "BLOCKED"
    radar_admission: str = "BLOCKED"
    paper_auto_ready: bool = False
    live_trade: bool = False


def review_tickflow_pilot(
    pilot: object,
    *,
    now_utc: datetime,
    account_entitlement_verified: bool = False,
    billing_units_verified: bool = False,
    request_charge_ceiling_approved: bool = False,
) -> TickFlowPilotReview:
    """Validate a proposed one-call test; even a PASS stays REVIEW_ONLY."""
    def stop(reason: str) -> TickFlowPilotReview:
        return TickFlowPilotReview("BLOCKED", reason)

    if not isinstance(pilot, TickFlowHistoryPilot):
        return stop("PILOT_UNKNOWN")
    if (
        not isinstance(now_utc, datetime) or now_utc.tzinfo is None
        or now_utc.utcoffset() is None
        or not isinstance(pilot.start_utc, datetime)
        or pilot.start_utc.tzinfo is None or pilot.start_utc.utcoffset() is None
        or not isinstance(pilot.end_utc, datetime)
        or pilot.end_utc.tzinfo is None or pilot.end_utc.utcoffset() is None
    ):
        return stop("TIMEZONE_EVIDENCE_REQUIRED")
    start = pilot.start_utc.astimezone(timezone.utc)
    end = pilot.end_utc.astimezone(timezone.utc)
    now = now_utc.astimezone(timezone.utc)
    if not start < end <= now or start < now - timedelta(days=_MINUTE_HISTORY_DAYS):
        return stop("WINDOW_OUTSIDE_ENTITLEMENT")
    if end - start > timedelta(days=1):
        return stop("PILOT_WINDOW_MORE_THAN_ONE_DAY")
    if (
        not isinstance(pilot.symbols, tuple)
        or not 1 <= len(pilot.symbols) <= 5
        or any(not isinstance(s, str) or _SYMBOL.fullmatch(s) is None for s in pilot.symbols)
        or len(set(pilot.symbols)) != len(pilot.symbols)
    ):
        return stop("PILOT_SYMBOLS_INVALID")
    if pilot.timeframe not in _TIMEFRAMES:
        return stop("PILOT_TIMEFRAME_UNSUPPORTED")
    if type(pilot.max_provider_requests) is not int or pilot.max_provider_requests != 1:
        return stop("PILOT_MAX_REQUESTS_NOT_ONE")
    if account_entitlement_verified is not True:
        return stop("ACCOUNT_ENTITLEMENT_UNVERIFIED")
    if billing_units_verified is not True:
        return stop("BILLING_UNITS_UNVERIFIED")
    if request_charge_ceiling_approved is not True:
        return stop("PAID_REQUEST_NOT_APPROVED")
    return TickFlowPilotReview(
        "REVIEW_ONLY", "NO_NETWORK_OR_LEDGER_AUTHORITY",
        len(pilot.symbols), pilot.max_provider_requests,
    )
