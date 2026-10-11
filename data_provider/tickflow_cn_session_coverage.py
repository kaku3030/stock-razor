"""Pure A-share ETF minute-session coverage review for future TickFlow batches.

Only checks caller-supplied sanitized HistoryRow timestamps. No SDK,
requests, local provider/credentials, trading-calendar discovery, or source
admission. Even complete coverage remains REVIEW_ONLY.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Sequence

from .tickflow_history_contract import HistoryRow

_SHANGHAI = timezone(timedelta(hours=8))
_MINUTE_PERIODS = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}
_SYMBOL = re.compile(r"[0-9]{6}\.(?:SH|SZ)\Z")
_MAX_SYMBOLS = 5
_MAX_BARS = _MAX_SYMBOLS * 240


@dataclass(frozen=True)
class AShareSessionCoverage:
    status: str
    reason: str
    expected_bars: int = 0
    observed_bars: int = 0
    missing_bars: int = 0
    unexpected_bars: int = 0
    duplicate_bars: int = 0
    provider_calls: int = 0
    provider_quota_reserved: int = 0
    source_arbiter_admission: str = "BLOCKED"
    radar_admission: str = "BLOCKED"
    paper_auto_ready: bool = False
    live_trade: bool = False


def _session_labels(
    trading_day: date, minutes: int, semantic: str,
) -> set[datetime]:
    """Bar start/end labels for the regular SSE/SZSE 240-minute ETF day."""
    labels: set[datetime] = set()
    offset = minutes if semantic == "BAR_END" else 0
    for opening in (time(9, 30), time(13, 0)):
        start = datetime.combine(trading_day, opening, tzinfo=_SHANGHAI)
        for elapsed in range(0, 120, minutes):
            labels.add(start + timedelta(minutes=elapsed + offset))
    return labels


def review_a_share_minute_session(
    rows: Sequence[HistoryRow],
    *,
    expected_symbols: tuple[str, ...],
    trading_day: date,
    timeframe: str,
    timestamp_semantic: str,
    trading_session_confirmed: bool = False,
    timestamp_semantic_verified: bool = False,
) -> AShareSessionCoverage:
    """Assess one **known** full regular session; no data-source promotion."""
    def stop(status: str, reason: str) -> AShareSessionCoverage:
        return AShareSessionCoverage(status, reason)

    if type(trading_day) is not date or trading_day.weekday() >= 5:
        return stop("UNKNOWN", "TRADING_DAY_CALENDAR_UNVERIFIED")
    if not isinstance(timeframe, str) or timeframe not in _MINUTE_PERIODS:
        return stop("BLOCKED", "UNSUPPORTED_MINUTE_TIMEFRAME")
    if timestamp_semantic not in ("BAR_START", "BAR_END"):
        return stop("UNKNOWN", "TIMESTAMP_SEMANTIC_UNKNOWN")
    if not (
        isinstance(expected_symbols, tuple)
        and 1 <= len(expected_symbols) <= _MAX_SYMBOLS
        and all(isinstance(x, str) and _SYMBOL.fullmatch(x) for x in expected_symbols)
        and len(set(expected_symbols)) == len(expected_symbols)
    ):
        return stop("BLOCKED", "INVALID_ETF_SYMBOL_SET")
    if not isinstance(rows, (tuple, list)) or len(rows) > _MAX_BARS:
        return stop("BLOCKED", "INVALID_OR_OVERSIZED_ROWS")
    if trading_session_confirmed is not True:
        return stop("UNKNOWN", "TRADING_SESSION_CONFIRMATION_MISSING")
    if timestamp_semantic_verified is not True:
        return stop("UNKNOWN", "TIMESTAMP_SEMANTIC_NOT_VERIFIED")

    labels = _session_labels(
        trading_day, _MINUTE_PERIODS[timeframe], timestamp_semantic
    )
    expected = {(symbol, label) for symbol in expected_symbols for label in labels}
    observed: set[tuple[str, datetime]] = set()
    duplicates = 0
    unexpected = 0
    for row in rows:
        if (
            not isinstance(row, HistoryRow)
            or row.source != "TICKFLOW"
            or row.symbol not in expected_symbols
            or not isinstance(row.timestamp, datetime)
            or row.timestamp.tzinfo is None
            or row.timestamp.utcoffset() is None
        ):
            return stop("BLOCKED", "INVALID_ROW_OR_SOURCE")
        key = row.symbol, row.timestamp.astimezone(_SHANGHAI)
        if key not in expected:
            unexpected += 1
        elif key in observed:
            duplicates += 1
        else:
            observed.add(key)

    missing = len(expected - observed)
    expected_count = len(expected)
    report = dict(
        expected_bars=expected_count,
        observed_bars=len(rows),
        missing_bars=missing,
        unexpected_bars=unexpected,
        duplicate_bars=duplicates,
    )
    if unexpected or duplicates or missing:
        return AShareSessionCoverage(
            "BLOCKED", "MINUTE_SESSION_GRID_MISMATCH", **report
        )
    return AShareSessionCoverage(
        "REVIEW_ONLY", "COVERAGE_ONLY_NOT_PRIMARY_SOURCE_QUALIFICATION",
        **report,
    )
