from __future__ import annotations
from datetime import timedelta, timezone
from data_provider.market_data_adapter import Bar, evaluate_health
from .futu_k1m_forming_accumulator import FormingMinuteBar


def closed_futu_minute_to_bar(minute: FormingMinuteBar, *, received_at):
    """Normalize only closure-proven OpenD minutes for research aggregation."""
    if not minute.is_closed:
        raise ValueError("forming OpenD minute cannot enter closed research history")
    start = minute.start.replace(tzinfo=None).replace(tzinfo=timezone.utc) if minute.start.tzinfo is None else minute.start
    # Futu US time_key is exchange-local; timezone binding remains unverified here.
    health = evaluate_health(freshness=0.5, completeness=1, timestamp=0.5, provider=1, continuity=0.5, cross_check=0.5, quality_flags=("TIMESTAMP_MISMATCH", "TIMESTAMP_SEMANTICS_UNVERIFIED",))
    return Bar(symbol=minute.symbol, market="us", asset_type="stock", timeframe="1m", bar_start=start, bar_end=start+timedelta(minutes=1), open=minute.open, high=minute.high, low=minute.low, close=minute.close, volume=minute.volume, amount=minute.turnover, provider="futu", source_timestamp=start, received_at=received_at, session="regular", is_closed=True, is_complete=True, feed="opend", health=health, quality_flags=health.quality_flags)

