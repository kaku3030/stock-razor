from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping
from zoneinfo import ZoneInfo

from data_provider.market_data_adapter import Bar, evaluate_health


FUTU_US_KLINE_TIMEZONE = ZoneInfo("America/New_York")


def historical_futu_k1m_to_bar(
    row: Mapping[str, object],
    *,
    received_at: datetime,
) -> Bar:
    """Normalize one read-only OpenD historical K_1M row for warm-start only.

    Historical rows may seed technical lookback, but they never establish
    realtime currentness, live bar-closure qualification, or admission.
    """

    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")

    symbol = str(row.get("code") or "").strip()
    raw_time = str(row.get("time_key") or "").strip()
    if not symbol.startswith("US.") or not raw_time:
        raise ValueError("canonical US code and time_key are required")

    end_local = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=FUTU_US_KLINE_TIMEZONE
    )
    end = end_local.astimezone(timezone.utc)
    start = end - timedelta(minutes=1)
    received = received_at.astimezone(timezone.utc)
    age_ms = max(0, round((received - end).total_seconds() * 1000))

    health = evaluate_health(
        freshness=0,
        completeness=1,
        timestamp=1,
        provider=1,
        continuity=0.5,
        cross_check=0.5,
        quality_flags=("HISTORICAL_QUERY", "STALE"),
    )

    return Bar(
        symbol=symbol,
        market="us",
        asset_type="stock",
        timeframe="1m",
        bar_start=start,
        bar_end=end,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row.get("volume") or 0),
        amount=(
            float(row["turnover"])
            if row.get("turnover") is not None
            else None
        ),
        provider="futu",
        feed="opend",
        source_timestamp=end,
        received_at=received,
        session="regular",
        is_closed=True,
        is_complete=True,
        latency_ms=age_ms,
        freshness_ms=age_ms,
        health=health,
        quality_flags=health.quality_flags,
    )
