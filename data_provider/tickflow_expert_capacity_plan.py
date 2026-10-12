"""Zero-I/O TickFlow Expert ¥199/month published-rate envelope planning.

Limits below were transcribed from the operator's 2026-10-11 plan screenshot.
They are NOT independently verified for the actual TickFlow account, and
planning does not reserve quota, bill an API, place orders or admit data.
Actual AWS/Windows processes share the same account allowance. This
pure planner has no cross-host scheduler or rate-limit enforcement.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
import re

_SYMBOL = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)\Z")
MAX_UNIVERSE = 10_000
ROWS_PER_REQUEST_CEILING = 10_000
PLAN_SOURCE = "USER_EXPERT_199_CNY_MONTH_SCREENSHOT_20261011_NOT_ACCOUNT_VERIFIED"

# Endpoint class: (published requests/minute, published symbols/request).
# These are user-supplied advertised limits, not a promise of shared quota
# independence, entitlement, per-minute billing or available capacity.
_ADVERTISED = {
    "realtime_quote_batch": (300, 500),
    "daily_kline_batch": (120, 200),
    "minute_kline_batch": (60, 200),
    "minute_kline_single": (120, 1),
    "websocket_quotes": (None, 200),
}
_MINUTE_PERIODS = frozenset(("1m", "5m", "15m", "30m", "60m"))
_MAX_MINUTE_HISTORY_DAYS = 365
_MAX_WS_SYMBOLS_PER_SOCKET = 200


@dataclass(frozen=True)
class TickFlowCapacityReview:
    status: str
    reason: str
    endpoint: str = ""
    advertised_source: str = PLAN_SOURCE
    symbol_count: int = 0
    estimated_rows_per_symbol: int = 0
    max_symbols_per_request: int = 0
    planned_requests: int = 0
    advertised_requests_per_minute: int = 0
    recommended_requests_per_minute: int = 0
    estimated_minimum_minutes: int = 0
    proposed_ws_connections: int = 0
    provider_requests: int = 0
    quota_reserved: int = 0
    data_qualification: str = "NOT_VERIFIED"
    account_entitlement: str = "NOT_VERIFIED"
    shared_account_coordination: str = "NOT_IMPLEMENTED"
    source_arbiter_admission: str = "BLOCKED"
    radar_admission: str = "BLOCKED"
    paper_auto_ready: bool = False
    live_trade: bool = False


def plan_tickflow_expert_capacity(
    symbols: tuple[str, ...],
    *,
    endpoint: str,
    estimated_rows_per_symbol: int = 1,
    minute_history_days: int = 1,
    minute_period: str = "15m",
    headroom_percent: int = 25,
) -> TickFlowCapacityReview:
    """Count future batches. NEVER issue provider calls or approve a source."""
    def stop(status: str, reason: str) -> TickFlowCapacityReview:
        return TickFlowCapacityReview(status=status, reason=reason, endpoint=endpoint)

    if not isinstance(endpoint, str) or endpoint not in _ADVERTISED:
        return stop("BLOCKED", "ENDPOINT_CLASS_UNSUPPORTED")
    if (
        not isinstance(symbols, tuple)
        or not 1 <= len(symbols) <= MAX_UNIVERSE
        or any(not isinstance(s, str) or _SYMBOL.fullmatch(s) is None for s in symbols)
        or len(set(symbols)) != len(symbols)
    ):
        return stop("BLOCKED", "SYMBOL_UNIVERSE_INVALID")
    if type(headroom_percent) is not int or not 0 <= headroom_percent <= 50:
        return stop("BLOCKED", "HEADROOM_PERCENT_INVALID")
    if type(estimated_rows_per_symbol) is not int or not 1 <= estimated_rows_per_symbol <= ROWS_PER_REQUEST_CEILING:
        return stop("UNKNOWN", "ROWS_PER_SYMBOL_UNVERIFIED_OR_TOO_LARGE")
    if endpoint.startswith("minute_kline"):
        if (
            type(minute_history_days) is not int
            or not 1 <= minute_history_days <= _MAX_MINUTE_HISTORY_DAYS
            or minute_period not in _MINUTE_PERIODS
        ):
            return stop("BLOCKED", "MINUTE_ENTITLEMENT_WINDOW_INVALID")
    elif minute_history_days != 1 or minute_period != "15m":
        return stop("BLOCKED", "MINUTE_SETTINGS_NOT_APPLICABLE")

    requests_per_minute, symbols_cap = _ADVERTISED[endpoint]
    count = len(symbols)
    if endpoint == "websocket_quotes":
        connections = ceil(count / _MAX_WS_SYMBOLS_PER_SOCKET)
        return TickFlowCapacityReview(
            "UNKNOWN", "WEBSOCKET_CONNECTION_AND_ACCOUNT_QUOTA_UNVERIFIED",
            endpoint=endpoint, symbol_count=count,
            estimated_rows_per_symbol=estimated_rows_per_symbol,
            max_symbols_per_request=symbols_cap,
            proposed_ws_connections=connections,
        )
    if endpoint == "minute_kline_single" and count != 1:
        return stop("BLOCKED", "SINGLE_MINUTE_ENDPOINT_REQUIRES_ONE_SYMBOL")

    # A 200-symbol minute request may violate the 10,000-row ceiling
    # for a full 240-bar 1m day. Split by both independent dimensions.
    row_limited_batch = ROWS_PER_REQUEST_CEILING // estimated_rows_per_symbol
    if row_limited_batch < 1:
        return stop("BLOCKED", "ROW_COUNT_OVER_SINGLE_REQUEST_LIMIT")
    batch = min(symbols_cap, row_limited_batch)
    requests = ceil(count / batch)
    target = max(1, requests_per_minute * (100 - headroom_percent) // 100)
    return TickFlowCapacityReview(
        status="REVIEW_ONLY",
        reason="ACCOUNT_SHARED_RUNTIME_LIMITER_AND_ENTITLEMENT_NOT_VERIFIED",
        endpoint=endpoint,
        symbol_count=count,
        estimated_rows_per_symbol=estimated_rows_per_symbol,
        max_symbols_per_request=batch,
        planned_requests=requests,
        advertised_requests_per_minute=requests_per_minute,
        recommended_requests_per_minute=target,
        estimated_minimum_minutes=ceil(requests / target),
    )
