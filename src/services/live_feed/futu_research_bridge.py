from __future__ import annotations
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo
from data_provider.market_data_adapter import Bar, evaluate_health
from .futu_k1m_forming_accumulator import FormingMinuteBar


FUTU_US_KLINE_TIMEZONE = ZoneInfo("America/New_York")


def closed_futu_minute_to_bar(minute: FormingMinuteBar, *, received_at):
    """Normalize only closure-proven OpenD minutes for research aggregation."""
    if not minute.is_closed:
        raise ValueError("forming OpenD minute cannot enter closed research history")
    # Futu API v10.11 documents US K-line time_key in US Eastern time.
    # This verifies timezone binding only; bar-boundary/currentness semantics
    # remain unqualified and must stay fail-closed.
    if minute.start.tzinfo is None:
        start = minute.start.replace(tzinfo=FUTU_US_KLINE_TIMEZONE).astimezone(timezone.utc)
    else:
        start = minute.start.astimezone(timezone.utc)
    health = evaluate_health(freshness=0.5, completeness=1, timestamp=0.5, provider=1, continuity=0.5, cross_check=0.5, quality_flags=("TIMESTAMP_SEMANTICS_UNVERIFIED",))
    return Bar(symbol=minute.symbol, market="us", asset_type="stock", timeframe="1m", bar_start=start, bar_end=start+timedelta(minutes=1), open=minute.open, high=minute.high, low=minute.low, close=minute.close, volume=minute.volume, amount=minute.turnover, provider="futu", source_timestamp=start, received_at=received_at, session="regular", is_closed=True, is_complete=True, feed="opend", health=health, quality_flags=health.quality_flags)

