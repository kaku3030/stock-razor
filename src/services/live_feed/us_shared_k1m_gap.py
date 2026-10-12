"""Read-only detection of correlated, *interior* US OpenD K1M gaps.

A shared hole across independent symbols is only a root-cause triage clue:
no synthetic repair, no provider calls and no realtime/Radar promotion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from data_provider.market_data_adapter import Bar


EASTERN = ZoneInfo("America/New_York")
US_START = time(9, 30)
US_END = time(16, 0)
ONE_MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class SharedMinuteGapAudit:
    status: str
    reason: str
    symbol_count: int
    common_observed_minutes: int
    missing_in_all_symbols_utc: tuple[str, ...] = ()
    research_only: bool = True
    root_cause_proven: bool = False
    provider_live_qualified: bool = False
    bar_closure_promotion_authorized: bool = False
    radar_admission: str = "BLOCKED"
    source_arbiter_admission: str = "BLOCKED"
    paper_auto_ready: bool = False
    live_trade: str = "NO"
    trade_execution: str = "NO"


def audit_shared_us_k1m_interior_gaps(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    *,
    symbols: Sequence[str],
    as_of: datetime,
) -> SharedMinuteGapAudit:
    """Correlate canonical closed K1M bars, excluding open/trailing buckets.

    `as_of` defines the RTH date and upper bound, not a guarantee that a
    provider has delivered its final minute. For that reason only gaps
    strictly between bars independently observed for *every* symbol count.
    """
    def unknown(reason: str, *, n: int = 0) -> SharedMinuteGapAudit:
        return SharedMinuteGapAudit("UNKNOWN", reason, n, 0)

    if (
        not isinstance(as_of, datetime)
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
    ):
        return unknown("OBSERVATION_TIME_UNVERIFIED")
    if (
        not isinstance(symbols, (tuple, list))
        or not 2 <= len(symbols) <= 20
        or any(
            not isinstance(symbol, str)
            or not symbol.startswith("US.")
            or not symbol[3:].replace(".", "").isalnum()
            or symbol != symbol.upper()
            for symbol in symbols
        )
        or len(set(symbols)) != len(symbols)
        or not isinstance(bars_by_symbol, Mapping)
    ):
        return unknown("EXPECTED_SYMBOL_SET_INVALID")

    local = as_of.astimezone(EASTERN)
    session_start = datetime.combine(local.date(), US_START, tzinfo=EASTERN)
    session_end = datetime.combine(local.date(), US_END, tzinfo=EASTERN)
    eligible_end = min(local, session_end)
    if eligible_end <= session_start + ONE_MINUTE:
        return unknown("INSUFFICIENT_ENDED_SESSION", n=len(symbols))

    observed: list[set[datetime]] = []
    starts: list[datetime] = []
    ends: list[datetime] = []
    for symbol in symbols:
        rows = bars_by_symbol.get(symbol)
        if not isinstance(rows, (tuple, list)):
            return unknown("CANONICAL_ROWS_UNAVAILABLE", n=len(symbols))
        stamps: set[datetime] = set()
        for bar in rows:
            if not isinstance(bar, Bar):
                return unknown("CANONICAL_BAR_INVALID", n=len(symbols))
            if not isinstance(bar.bar_start, datetime) or not isinstance(bar.bar_end, datetime):
                return unknown("CANONICAL_BAR_INVALID", n=len(symbols))
            if (
                bar.bar_start.tzinfo is None
                or bar.bar_end.tzinfo is None
                or not isinstance(bar.source_timestamp, datetime)
                or bar.source_timestamp.tzinfo is None
                or bar.bar_start.utcoffset() is None
                or bar.bar_end.utcoffset() is None
                or bar.source_timestamp.utcoffset() is None
            ):
                return unknown("CANONICAL_BAR_TIMEZONE_INVALID", n=len(symbols))
            start = bar.bar_start.astimezone(EASTERN)
            end = bar.bar_end.astimezone(EASTERN)
            if start.date() != local.date():
                continue  # Historical bars cannot fill today's session.
            if not session_start <= start < end <= session_end:
                return unknown("CANONICAL_SESSION_GRID_INVALID", n=len(symbols))
            if (
                bar.symbol != symbol
                or bar.market != "us"
                or bar.timeframe != "1m"
                or bar.provider != "futu"
                or bar.feed != "opend"
                or bar.session != "regular"
                or bar.is_closed is not True
                or bar.is_complete is not True
                or end - start != ONE_MINUTE
                or end > eligible_end
                or bar.source_timestamp.astimezone(EASTERN) != end
                or not isinstance(bar.quality_flags, (tuple, list))
                or any(
                    flag in {"MISSING_BAR", "PARTIAL_BAR", "TIMESTAMP_MISMATCH"}
                    for flag in bar.quality_flags
                )
            ):
                return unknown("CANONICAL_PROVENANCE_OR_CLOSURE_INVALID", n=len(symbols))
            if start in stamps:
                return unknown("DUPLICATE_MINUTE_EVIDENCE", n=len(symbols))
            stamps.add(start)
        if len(stamps) < 3:
            return unknown("INSUFFICIENT_CANONICAL_HISTORY", n=len(symbols))
        observed.append(stamps)
        starts.append(min(stamps))
        ends.append(max(stamps))

    overlap_start = max(starts)
    overlap_end = min(ends)
    if overlap_end - overlap_start < 2 * ONE_MINUTE:
        return unknown("INSUFFICIENT_SHARED_COVERAGE", n=len(symbols))
    # Missing boundary bars cannot be classed as an ingestion dropout until
    # a later provider-stamped bar is observed for every affected symbol.
    interior: list[datetime] = []
    cursor = overlap_start + ONE_MINUTE
    while cursor < overlap_end:
        interior.append(cursor)
        cursor += ONE_MINUTE
    shared = tuple(
        point.astimezone(timezone.utc).isoformat()
        for point in interior
        if all(point not in seen for seen in observed)
    )
    return SharedMinuteGapAudit(
        status="SHARED_GAP_OBSERVED" if shared else "NO_SHARED_GAP_OBSERVED",
        reason="CORRELATED_INTERIOR_K1M_GAP" if shared else "NO_CORRELATED_INTERIOR_K1M_GAP",
        symbol_count=len(symbols),
        common_observed_minutes=len(interior),
        missing_in_all_symbols_utc=shared,
    )
