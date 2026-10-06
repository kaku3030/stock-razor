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
    # AWS cross-check evidence shows US OpenD K-line time_key is the
    # interval END label (RTH K_1M runs 09:31..16:00; K_5M 09:35..16:00).
    # Futu v10.11 documents that label in US Eastern time. Currentness and
    # delivery qualification remain independent and therefore fail-closed.
    if minute.start.tzinfo is None:
        end = minute.start.replace(tzinfo=FUTU_US_KLINE_TIMEZONE).astimezone(timezone.utc)
    else:
        end = minute.start.astimezone(timezone.utc)
    start = end - timedelta(minutes=1)
    health = evaluate_health(freshness=0.5, completeness=1, timestamp=0.5, provider=1, continuity=0.5, cross_check=0.5, quality_flags=("TIMESTAMP_SEMANTICS_UNVERIFIED",))
    return Bar(symbol=minute.symbol, market="us", asset_type="stock", timeframe="1m", bar_start=start, bar_end=end, open=minute.open, high=minute.high, low=minute.low, close=minute.close, volume=minute.volume, amount=minute.turnover, provider="futu", source_timestamp=end, received_at=received_at, session="regular", is_closed=True, is_complete=True, feed="opend", health=health, quality_flags=health.quality_flags)

