from __future__ import annotations

from datetime import time, timedelta, timezone
from zoneinfo import ZoneInfo

from data_provider.market_data_adapter import Bar, evaluate_health

from .futu_k1m_forming_accumulator import FormingMinuteBar


FUTU_US_KLINE_TIMEZONE = ZoneInfo("America/New_York")
FUTU_US_K1M_FRESHNESS_LIMIT_SECONDS = 120
FUTU_US_K1M_FUTURE_SKEW_SECONDS = 5


def is_futu_us_rth_interval_end(interval_end) -> bool:
    """Classify an OpenD exchange-local interval-end without creating a bar."""
    if interval_end.tzinfo is None:
        local_end = interval_end
    else:
        local_end = interval_end.astimezone(FUTU_US_KLINE_TIMEZONE)
    return time(9, 31) <= local_end.time() <= time(16, 0)


def closed_futu_minute_to_bar(minute: FormingMinuteBar, *, received_at):
    """Normalize only closure-proven OpenD minutes for research aggregation.

    US OpenD intraday K-line time_key has already been qualified as the
    interval END label. Freshness is evaluated independently from timestamp
    semantics using the observed receive delay for this closed bar.
    """

    if not minute.is_closed:
        raise ValueError("forming OpenD minute cannot enter closed research history")
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")

    # Qualified provider semantics:
    # - US K_1M regular-session labels run 09:31..16:00 Eastern.
    # - The label is the interval END, so canonical start=end-1m.
    # - DST binding remains America/New_York.
    if minute.start.tzinfo is None:
        end = minute.start.replace(tzinfo=FUTU_US_KLINE_TIMEZONE).astimezone(timezone.utc)
    else:
        end = minute.start.astimezone(timezone.utc)
    # The OpenD stream may remain active in premarket or after-hours.
    # Do not mislabel those K_1M rows as RTH without a separately
    # qualified extended-session normalization contract.
    if not is_futu_us_rth_interval_end(minute.start):
        raise ValueError("US_RTH_END_LABEL_REQUIRED")
    start = end - timedelta(minutes=1)
    received = received_at.astimezone(timezone.utc)
    age_seconds = (received - end).total_seconds()

    flags: list[str] = []
    if age_seconds < -FUTU_US_K1M_FUTURE_SKEW_SECONDS:
        flags.append("TIMESTAMP_MISMATCH")
        freshness = 0
    elif age_seconds > FUTU_US_K1M_FRESHNESS_LIMIT_SECONDS:
        flags.append("STALE")
        freshness = 0
    else:
        freshness = 1

    # Reject an impossible source-minute turnover/VWAP before aggregation.
    # This keeps a bad provider numerator from being summed into a complete
    # higher-timeframe bar and makes the quality failure explicit.
    if minute.turnover is not None and minute.volume > 0:
        source_vwap = minute.turnover / minute.volume
        tolerance = max(1e-6, max(abs(minute.low), abs(minute.high)) * 1e-6)
        if not minute.low - tolerance <= source_vwap <= minute.high + tolerance:
            flags.append("VWAP_OUTSIDE_BAR_RANGE")

    # Timestamp semantics are now a proven provider fact. Continuity and
    # provider cross-check remain deliberately conservative here; they are
    # qualified independently by the runtime evidence layers.
    health = evaluate_health(
        freshness=freshness,
        completeness=1,
        timestamp=1,
        provider=1,
        continuity=0.5,
        cross_check=0.5,
        quality_flags=flags,
    )
    age_ms = max(0, round(age_seconds * 1000))

    return Bar(
        symbol=minute.symbol,
        market="us",
        asset_type="stock",
        timeframe="1m",
        bar_start=start,
        bar_end=end,
        open=minute.open,
        high=minute.high,
        low=minute.low,
        close=minute.close,
        volume=minute.volume,
        amount=(None if "VWAP_OUTSIDE_BAR_RANGE" in flags else minute.turnover),
        provider="futu",
        source_timestamp=end,
        received_at=received,
        session="regular",
        is_closed=True,
        is_complete=True,
        feed="opend",
        latency_ms=age_ms,
        freshness_ms=age_ms,
        health=health,
        quality_flags=health.quality_flags,
    )
