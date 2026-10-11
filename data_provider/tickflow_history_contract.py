"""Fail-closed contract for a future TickFlow paid history batch.

This module is intentionally independent from the TickFlow SDK and from the
existing provider fetcher.  It only gates a caller-supplied transport and
checks sanitized batch metadata after a transport call.  It never creates a
client, reads credentials, performs network I/O, or changes admission flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping


PASS = "PASS"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"

_CONSISTENT = "CONSISTENT"
_INCONSISTENT = "INCONSISTENT"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class HistoryBatchRequest:
    """The exact window and symbols a paid batch transport is asked to fetch."""

    symbols: tuple[str, ...]
    start_time: datetime
    end_time: datetime
    source: str = "TICKFLOW"


@dataclass(frozen=True)
class HistoryRow:
    """Sanitized row metadata required by the independent crosscheck."""

    symbol: str
    timestamp: datetime
    source: str


@dataclass(frozen=True)
class HistoryBatchResponse:
    """Transport response metadata; raw provider payloads are out of scope."""

    request_start_time: datetime | None
    request_end_time: datetime | None
    rows: tuple[HistoryRow, ...]
    row_count: int | None
    source: str | None
    source_consistency: str | None
    window_complete: bool | None


@dataclass
class PaidHistoryBudget:
    """Explicit opt-in budget and provider quota reservation for one request."""

    enabled: bool = False
    budget_remaining: int | None = None
    quota_remaining: int | None = None
    request_cost: int = 1

    def reserve(self) -> str | None:
        """Reserve one request, returning a fail-closed reason when refused."""
        if not self.enabled:
            return "DISABLED_DEFAULT"
        if type(self.request_cost) is not int or self.request_cost <= 0:
            return "INVALID_REQUEST_COST"
        if self.budget_remaining is None:
            return "BUDGET_UNKNOWN"
        if self.quota_remaining is None:
            return "QUOTA_UNKNOWN"
        if type(self.budget_remaining) is not int or self.budget_remaining < 0:
            return "INVALID_BUDGET"
        if type(self.quota_remaining) is not int or self.quota_remaining < 0:
            return "INVALID_QUOTA"
        if self.budget_remaining < self.request_cost:
            return "BUDGET_EXHAUSTED"
        if self.quota_remaining < self.request_cost:
            return "QUOTA_EXHAUSTED"
        self.budget_remaining -= self.request_cost
        self.quota_remaining -= self.request_cost
        return None


@dataclass(frozen=True)
class HistoryCrosscheck:
    status: str
    checks: Mapping[str, str]
    reason: str | None = None


@dataclass(frozen=True)
class HistoryBatchResult:
    status: str
    reason: str
    provider_requests: int
    crosscheck: HistoryCrosscheck | None
    budget_remaining: int | None
    quota_remaining: int | None


def _result(
    status: str,
    reason: str,
    *,
    provider_requests: int,
    budget: PaidHistoryBudget | None,
    crosscheck: HistoryCrosscheck | None = None,
) -> HistoryBatchResult:
    return HistoryBatchResult(
        status=status,
        reason=reason,
        provider_requests=provider_requests,
        crosscheck=crosscheck,
        budget_remaining=budget.budget_remaining if budget is not None else None,
        quota_remaining=budget.quota_remaining if budget is not None else None,
    )


def crosscheck_history_batch(
    request: HistoryBatchRequest,
    response: HistoryBatchResponse,
) -> HistoryCrosscheck:
    """Check request echo, symbols, timestamps, row count and source fields."""
    checks: dict[str, str] = {
        "request_window": UNKNOWN,
        "symbols": UNKNOWN,
        "timestamps": UNKNOWN,
        "row_count": UNKNOWN,
        "source_consistency": UNKNOWN,
        "window_completeness": UNKNOWN,
    }
    failures: list[str] = []
    unknowns: list[str] = []

    if request.source != "TICKFLOW":
        failures.append("INVALID_REQUEST_SOURCE")

    request_start = _as_utc(request.start_time)
    request_end = _as_utc(request.end_time)
    response_start = _as_utc(response.request_start_time)
    response_end = _as_utc(response.request_end_time)
    if request_start is None or request_end is None or request_start >= request_end:
        failures.append("INVALID_REQUEST_WINDOW")
        checks["request_window"] = BLOCKED
    elif response_start is None or response_end is None:
        unknowns.append("REQUEST_WINDOW_UNKNOWN")
    elif (response_start, response_end) != (request_start, request_end):
        failures.append("REQUEST_WINDOW_MISMATCH")
        checks["request_window"] = BLOCKED
    else:
        checks["request_window"] = PASS

    try:
        requested_symbols = tuple(request.symbols)
    except TypeError:
        requested_symbols = ()
    rows_are_valid = isinstance(response.rows, (tuple, list)) and all(
        isinstance(row, HistoryRow)
        and isinstance(row.symbol, str)
        and isinstance(row.source, str)
        for row in response.rows
    )
    returned_symbols = {row.symbol for row in response.rows} if rows_are_valid else set()
    if not requested_symbols or any(not isinstance(symbol, str) or not symbol for symbol in requested_symbols):
        failures.append("INVALID_REQUEST_SYMBOLS")
        checks["symbols"] = BLOCKED
    elif not rows_are_valid:
        failures.append("INVALID_RESPONSE_ROWS")
        checks["symbols"] = BLOCKED
    elif returned_symbols != set(requested_symbols):
        failures.append("SYMBOL_SET_MISMATCH")
        checks["symbols"] = BLOCKED
    else:
        checks["symbols"] = PASS

    per_symbol: dict[str, list[datetime]] = {}
    if rows_are_valid:
        for row in response.rows:
            timestamp = _as_utc(row.timestamp)
            if timestamp is None:
                failures.append("INVALID_TIMESTAMP")
                break
            if request_start is not None and request_end is not None and not (
                request_start <= timestamp <= request_end
            ):
                failures.append("TIMESTAMP_OUTSIDE_REQUEST_WINDOW")
                break
            per_symbol.setdefault(row.symbol, []).append(timestamp)
        else:
            if all(
                all(left < right for left, right in zip(values, values[1:]))
                for values in per_symbol.values()
            ):
                checks["timestamps"] = PASS
            else:
                failures.append("TIMESTAMP_NOT_STRICTLY_INCREASING")
    if checks["timestamps"] != PASS and not any(
        reason in failures
        for reason in (
            "INVALID_TIMESTAMP",
            "TIMESTAMP_OUTSIDE_REQUEST_WINDOW",
            "TIMESTAMP_NOT_STRICTLY_INCREASING",
        )
    ):
        unknowns.append("TIMESTAMPS_UNKNOWN")

    actual_row_count = len(response.rows) if isinstance(response.rows, (tuple, list)) else None
    if response.row_count is None:
        unknowns.append("ROW_COUNT_UNKNOWN")
    elif type(response.row_count) is not int or actual_row_count is None or response.row_count != actual_row_count:
        failures.append("ROW_COUNT_MISMATCH")
        checks["row_count"] = BLOCKED
    else:
        checks["row_count"] = PASS

    row_sources = {row.source for row in response.rows} if rows_are_valid else set()
    if response.source is None or response.source_consistency is None:
        unknowns.append("SOURCE_CONSISTENCY_UNKNOWN")
    elif response.source != request.source:
        failures.append("RESPONSE_SOURCE_MISMATCH")
        checks["source_consistency"] = BLOCKED
    elif response.source_consistency == _INCONSISTENT or row_sources != {response.source}:
        failures.append("CROSS_SOURCE_INCONSISTENCY")
        checks["source_consistency"] = BLOCKED
    elif response.source_consistency != _CONSISTENT:
        failures.append("INVALID_SOURCE_CONSISTENCY")
        checks["source_consistency"] = BLOCKED
    else:
        checks["source_consistency"] = PASS

    if response.window_complete is True:
        checks["window_completeness"] = PASS
    elif response.window_complete is False:
        failures.append("WINDOW_INCOMPLETE")
        checks["window_completeness"] = BLOCKED
    else:
        unknowns.append("WINDOW_COMPLETENESS_UNKNOWN")

    if failures:
        return HistoryCrosscheck(BLOCKED, checks, failures[0])
    if unknowns:
        return HistoryCrosscheck(UNKNOWN, checks, unknowns[0])
    return HistoryCrosscheck(PASS, checks)


def fetch_history_batch(
    request: HistoryBatchRequest,
    transport: Callable[[HistoryBatchRequest], HistoryBatchResponse],
    *,
    budget: PaidHistoryBudget | None = None,
) -> HistoryBatchResult:
    """Gate and crosscheck one future paid batch without owning its transport."""
    if budget is None:
        return _result(
            UNKNOWN,
            "BUDGET_UNKNOWN",
            provider_requests=0,
            budget=None,
        )

    refusal = budget.reserve()
    if refusal is not None:
        status = UNKNOWN if refusal.endswith("UNKNOWN") else BLOCKED
        return _result(status, refusal, provider_requests=0, budget=budget)

    try:
        response = transport(request)
    except Exception:
        return _result(
            UNKNOWN,
            "TRANSPORT_RESULT_UNKNOWN",
            provider_requests=1,
            budget=budget,
        )

    if not isinstance(response, HistoryBatchResponse):
        return _result(
            BLOCKED,
            "INVALID_RESPONSE_METADATA",
            provider_requests=1,
            budget=budget,
        )

    crosscheck = crosscheck_history_batch(request, response)
    return _result(
        crosscheck.status,
        crosscheck.reason or crosscheck.status,
        provider_requests=1,
        budget=budget,
        crosscheck=crosscheck,
    )


__all__ = [
    "BLOCKED",
    "HistoryBatchRequest",
    "HistoryBatchResponse",
    "HistoryBatchResult",
    "HistoryCrosscheck",
    "HistoryRow",
    "PaidHistoryBudget",
    "PASS",
    "UNKNOWN",
    "crosscheck_history_batch",
    "fetch_history_batch",
]
