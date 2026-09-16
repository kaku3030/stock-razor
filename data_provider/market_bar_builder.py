# -*- coding: utf-8 -*-
"""Deterministic, session-aware aggregation of normalized one-minute bars."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .market_data_adapter import Bar, evaluate_health


@dataclass(frozen=True)
class SessionWindow:
    name: str
    start: time
    end: time


MARKET_SESSIONS = {
    "cn": (
        SessionWindow("regular", time(9, 30), time(11, 30)),
        SessionWindow("regular", time(13, 0), time(15, 0)),
    ),
    "us": (SessionWindow("regular", time(9, 30), time(16, 0)),),
}

MARKET_TIMEZONES = {"cn": "Asia/Shanghai", "us": "America/New_York"}
TIMEFRAME_MINUTES = {"15m": 15, "1h": 60}


def _bucket_for(
    timestamp: datetime,
    *,
    market: str,
    minutes: int,
    sessions: tuple[SessionWindow, ...],
    timezone_name: str,
) -> tuple[datetime, datetime, str] | None:
    zone = ZoneInfo(timezone_name)
    local = timestamp.astimezone(zone)
    for session in sessions:
        session_start = datetime.combine(local.date(), session.start, zone)
        session_end = datetime.combine(local.date(), session.end, zone)
        if session_start <= local < session_end:
            offset_minutes = int((local - session_start).total_seconds() // 60)
            bucket_start = session_start + timedelta(minutes=(offset_minutes // minutes) * minutes)
            bucket_end = min(bucket_start + timedelta(minutes=minutes), session_end)
            return bucket_start, bucket_end, session.name
    return None


def aggregate_bars(
    bars: list[Bar],
    timeframe: str,
    *,
    as_of: datetime,
    sessions: tuple[SessionWindow, ...] | None = None,
    timezone_name: str | None = None,
    include_forming: bool = True,
) -> list[Bar]:
    """Aggregate 1m bars within one market/provider/feed, never across breaks.

    Duplicate source minutes use the latest ``received_at`` value, allowing a
    provider correction to replace an earlier minute deterministically. A
    complete source-minute grid and confirmed source bars are both necessary
    before the aggregate can be considered confirmed and complete.
    """

    if timeframe not in TIMEFRAME_MINUTES:
        raise ValueError(f"unsupported aggregate timeframe: {timeframe}")
    if not bars:
        return []
    market = bars[0].market
    provider = bars[0].provider
    feed = bars[0].feed
    if any(bar.market != market or bar.timeframe != "1m" for bar in bars):
        raise ValueError("all source bars must be 1m bars from the same market")
    if any(bar.provider != provider or bar.feed != feed for bar in bars):
        raise ValueError("all source bars must have the same provider and feed")

    resolved_sessions = sessions or MARKET_SESSIONS.get(market)
    resolved_timezone = timezone_name or MARKET_TIMEZONES.get(market)
    if not resolved_sessions or not resolved_timezone:
        raise ValueError(f"session definition required for market: {market}")

    latest_by_minute: dict[tuple[str, datetime], Bar] = {}
    for bar in bars:
        key = (bar.symbol, bar.bar_start)
        existing = latest_by_minute.get(key)
        if existing is None or bar.received_at >= existing.received_at:
            latest_by_minute[key] = bar

    grouped: dict[tuple[str, datetime, datetime, str], list[Bar]] = defaultdict(list)
    minutes = TIMEFRAME_MINUTES[timeframe]
    for bar in latest_by_minute.values():
        bucket = _bucket_for(
            bar.bar_start,
            market=market,
            minutes=minutes,
            sessions=resolved_sessions,
            timezone_name=resolved_timezone,
        )
        if bucket is not None:
            grouped[(bar.symbol, *bucket)].append(bar)

    result: list[Bar] = []
    for (symbol, bucket_start, bucket_end, session), source_bars in sorted(grouped.items()):
        ordered = sorted(source_bars, key=lambda item: item.bar_start)
        expected_count = int((bucket_end - bucket_start).total_seconds() // 60)
        expected_starts = {
            bucket_start + timedelta(minutes=offset) for offset in range(expected_count)
        }
        exact_minutes = (
            {item.bar_start for item in ordered} == expected_starts
            and all(item.bar_end == item.bar_start + timedelta(minutes=1) for item in ordered)
        )
        sources_closed = all(item.is_closed for item in ordered)
        closed = as_of.astimezone(bucket_end.tzinfo) >= bucket_end and sources_closed
        if not include_forming and not closed:
            continue
        complete = (
            len(ordered) == expected_count
            and exact_minutes
            and all(item.is_complete for item in ordered)
        )
        flags = list(dict.fromkeys(flag for item in ordered for flag in item.quality_flags))
        if not complete:
            flags.append("MISSING_BAR")
        if not closed:
            flags.append("PARTIAL_BAR")
        if feed is None:
            flags.append("FEED_UNVERIFIED")

        volume = sum(item.volume for item in ordered)
        amounts = [item.amount for item in ordered]
        amount = sum(value for value in amounts if value is not None) if any(value is not None for value in amounts) else None
        health = evaluate_health(
            freshness=0 if "STALE" in flags else 1,
            completeness=min(len(ordered) / expected_count, 1) if complete else min(len(ordered) / expected_count, 0.5),
            timestamp=0 if "TIMESTAMP_MISMATCH" in flags else 1,
            provider=1 if feed is not None else 0,
            continuity=1 if complete else min(len(ordered) / expected_count, 0.5),
            cross_check=0.5 if feed is not None else 0,
            quality_flags=flags,
        )
        result.append(
            Bar(
                symbol=symbol,
                market=market,
                asset_type=ordered[0].asset_type,
                timeframe=timeframe,
                bar_start=bucket_start,
                bar_end=bucket_end,
                open=ordered[0].open,
                high=max(item.high for item in ordered),
                low=min(item.low for item in ordered),
                close=ordered[-1].close,
                volume=volume,
                amount=amount,
                vwap=(amount / volume) if amount is not None and volume > 0 else None,
                provider=provider,
                feed=feed,
                session=session,
                source_timestamp=max(item.source_timestamp for item in ordered),
                received_at=max(item.received_at for item in ordered),
                is_closed=closed,
                is_complete=complete,
                latency_ms=max(item.latency_ms for item in ordered),
                freshness_ms=max(item.freshness_ms for item in ordered),
                health=health,
                quality_flags=health.quality_flags,
            )
        )
    return result
