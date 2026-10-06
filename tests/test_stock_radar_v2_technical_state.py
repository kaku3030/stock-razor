from datetime import datetime, timedelta, timezone

import pandas as pd

from data_provider.market_data_adapter import Bar, SignalPermission, evaluate_health
from src.services.realtime_market_data import MarketDataSnapshot
from src.services.stock_radar_v2.technical_state import StockRadarTechnicalStateService


START = datetime(2026, 8, 31, 13, 30, tzinfo=timezone.utc)
HEALTHY = evaluate_health(
    freshness=1,
    completeness=1,
    timestamp=1,
    provider=1,
    continuity=1,
    cross_check=1,
)


def _bar(index: int, timeframe: str, *, partial: bool = False) -> Bar:
    minutes = 15 if timeframe == "15m" else 60
    start = START + timedelta(minutes=index * minutes)
    close = 100 + index * 0.5
    return Bar(
        symbol="NVDA",
        market="us",
        asset_type="stock",
        timeframe=timeframe,
        bar_start=start,
        bar_end=start + timedelta(minutes=minutes),
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000 + index,
        provider="alpaca",
        feed="iex",
        source_timestamp=start + timedelta(minutes=minutes),
        received_at=start + timedelta(minutes=minutes),
        session="regular",
        is_closed=not partial,
        is_complete=not partial,
        health=HEALTHY,
        quality_flags=("PARTIAL_BAR",) if partial else (),
    )


def _daily(count: int = 80) -> pd.DataFrame:
    close = [100 + index * 0.5 for index in range(count)]
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-05-01", periods=count, freq="D"),
            "open": close,
            "high": [value + 1 for value in close],
            "low": [value - 1 for value in close],
            "close": close,
            "volume": [1000 + index for index in range(count)],
        }
    )


def _snapshot(*, partial: bool = False, health=HEALTHY) -> MarketDataSnapshot:
    bars_15m = tuple(_bar(index, "15m", partial=partial and index == 39) for index in range(40))
    bars_1h = tuple(_bar(index, "1h") for index in range(40))
    return MarketDataSnapshot(
        symbol="NVDA",
        as_of=START + timedelta(days=3),
        minute_bars=(),
        bars_5m=(),
        bars_15m=bars_15m,
        bars_1h=bars_1h,
        health=health,
        provider="alpaca",
        feed="iex",
        fallback_from=None,
        fallback_reason=None,
    )


def test_bridge_builds_all_timeframes_without_confirming_signal() -> None:
    state = StockRadarTechnicalStateService().evaluate(_snapshot(), daily=_daily())

    assert state.technical.daily.trend == "bullish"
    assert state.technical.hourly.trend == "bullish"
    assert state.technical.intraday.trend == "bullish"
    assert state.signal_permission is SignalPermission.NORMAL
    assert state.research_only is True
    assert state.can_confirm_signal is False
    assert "buy_signal" not in state.to_dict()


def test_forming_bar_is_partial_and_caps_intraday_confidence() -> None:
    state = StockRadarTechnicalStateService().evaluate(_snapshot(partial=True), daily=_daily())

    assert state.technical.intraday.quality.is_partial_bar is True
    assert state.technical.intraday.confidence <= 0.65
    assert "15m_partial_bar" in state.technical.risk_flags


def test_missing_daily_data_degrades_without_inventing_daily_state() -> None:
    state = StockRadarTechnicalStateService().evaluate(_snapshot())

    assert state.technical.daily.trend == "unknown"
    assert "1d_data_missing" in state.technical.risk_flags


def test_blocked_health_permission_is_preserved() -> None:
    blocked = evaluate_health(
        freshness=1,
        completeness=1,
        timestamp=1,
        provider=1,
        continuity=1,
        cross_check=1,
        quality_flags=["INVALID_OHLC"],
    )

    state = StockRadarTechnicalStateService().evaluate(_snapshot(health=blocked), daily=_daily())

    assert state.signal_permission is SignalPermission.BLOCKED
    assert state.data_health_score <= 49
    assert "invalid_ohlc" in state.technical.risk_flags
