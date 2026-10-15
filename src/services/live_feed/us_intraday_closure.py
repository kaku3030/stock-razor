from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from data_provider.market_data_adapter import Bar


US_EASTERN = ZoneInfo("America/New_York")
US_SESSION_START = time(9, 30)
US_SESSION_END = time(16, 0)


def qualify_us_current_session_intraday_closure(
    bars_by_timeframe: dict[str, list[Bar]], *, as_of: datetime
) -> dict[str, object]:
    """Qualify only closed, contiguous bars observed for today's US session.

    This is research evidence from the canonical 1m-derived cache. It does
    not establish provider entitlement, realtime delivery, or trading
    readiness.
    """

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    observed = as_of.astimezone(US_EASTERN)
    session_date = observed.date().isoformat()
    session_start = datetime.combine(observed.date(), US_SESSION_START, US_EASTERN)
    session_end = datetime.combine(observed.date(), US_SESSION_END, US_EASTERN)
    timeframes: dict[str, dict[str, object]] = {}
    evidence: dict[str, object] = {
        "session_date": session_date,
        "session_timezone": "America/New_York",
        "session_start_utc": session_start.astimezone(ZoneInfo("UTC")).isoformat(),
        "session_end_utc": session_end.astimezone(ZoneInfo("UTC")).isoformat(),
        "as_of_utc": as_of.astimezone(ZoneInfo("UTC")).isoformat(),
        "status": "UNKNOWN",
        "reason": "NO_CURRENT_SESSION_BARS",
        "timeframes": timeframes,
        "research_only": True,
        "bar_closure_promotion_authorized": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }
    for timeframe, minutes in (("15m", 15), ("1h", 60)):
        bars = [
            bar
            for bar in bars_by_timeframe.get(timeframe, [])
            if bar.bar_end.astimezone(US_EASTERN).date() == observed.date()
            and bar.session == "regular"
        ]
        bars.sort(key=lambda bar: bar.bar_start)
        eligible_end = min(observed, session_end)
        # Only buckets that have ENDED by as_of can prove closure. The
        # current live 15m/1h bucket is legitimately forming during RTH;
        # including it in invalid would make the whole session UNKNOWN on
        # every healthy intra-bucket observation. Never ignore a prematurely
        # closed bar or an already-ended but incomplete bucket.
        closed = [
            bar for bar in bars
            if bar.is_closed and bar.is_complete
            and bar.bar_end.astimezone(US_EASTERN) <= eligible_end
        ]
        expected = []
        cursor = session_start
        while cursor < eligible_end:
            end = min(cursor + timedelta(minutes=minutes), session_end)
            if end <= eligible_end:
                expected.append((cursor, end))
            cursor = end
        actual = {(bar.bar_start.astimezone(US_EASTERN), bar.bar_end.astimezone(US_EASTERN)) for bar in closed}
        missing = [start.isoformat() for start, end in expected if (start, end) not in actual]
        invalid: list[str] = []
        current_forming_excluded = 0
        for bar in bars:
            local_start = bar.bar_start.astimezone(US_EASTERN)
            local_end = bar.bar_end.astimezone(US_EASTERN)
            current_forming = (
                bar.is_closed is False
                and bar.is_complete is False
                and bar.provider == "futu"
                and bar.feed == "opend"
                and bar.timeframe == timeframe
                and session_start <= local_start <= eligible_end < local_end <= session_end
                and local_end == min(local_start + timedelta(minutes=minutes), session_end)
                and (local_start - session_start).total_seconds() % (minutes * 60) == 0
            )
            if current_forming:
                current_forming_excluded += 1
                # Duplicate current buckets are not an authoritative
                # provider bar grid and must never turn the gate green.
                if current_forming_excluded > 1:
                    invalid.append(local_start.isoformat())
                continue
            if (
                not bar.is_closed
                or not bar.is_complete
                or bar.provider != "futu"
                or bar.feed != "opend"
                or bar.timeframe != timeframe
                # A full same-OpenD historical postclose grid may repair the
                # 16:00 research cache. It cannot prove realtime close.
                or "HISTORICAL_QUERY" in bar.quality_flags
                or local_end > eligible_end
                or bar.source_timestamp.astimezone(US_EASTERN) != local_end
            ):
                invalid.append(local_start.isoformat())
        timeframe_status = "PASS" if expected and not missing and not invalid else "UNKNOWN"
        reason = "CURRENT_SESSION_CLOSED_GRID_COMPLETE" if timeframe_status == "PASS" else (
            "INVALID_OR_FORMING_BARS" if invalid else "MISSING_CURRENT_SESSION_BARS"
        )
        timeframes[timeframe] = {
            "status": timeframe_status,
            "reason": reason,
            "expected_closed_count": len(expected),
            "observed_closed_count": len(closed),
            "current_forming_excluded_count": current_forming_excluded,
            "missing_bar_starts": missing,
            "invalid_bar_starts": invalid,
            "latest_closed_bar_end_utc": (
                closed[-1].bar_end.astimezone(ZoneInfo("UTC")).isoformat() if closed else None
            ),
        }
    timeframe_values = timeframes.values()
    if all(item["status"] == "PASS" for item in timeframe_values):
        evidence["status"] = "PASS"
        evidence["reason"] = "CURRENT_SESSION_15M_60M_CLOSED_GRIDS_COMPLETE"
    return evidence
