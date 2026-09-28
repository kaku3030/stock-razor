"""Fail-closed data integrity regressions; no network or provider credentials."""

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from data_provider.market_bar_builder import aggregate_bars
from data_provider.market_data_adapter import Bar, SignalPermission


CN = ZoneInfo("Asia/Shanghai")
START = datetime(2026, 9, 17, 9, 30, tzinfo=CN)
AS_OF = datetime(2026, 9, 17, 9, 45, tzinfo=CN)


def minutes(*, feed="iex", provider="alpaca") -> list[Bar]:
    return [
        Bar(
            symbol="NVDA",
            market="cn",
            asset_type="stock",
            timeframe="1m",
            bar_start=START + timedelta(minutes=offset),
            bar_end=START + timedelta(minutes=offset + 1),
            open=10.0,
            high=11.0,
            low=9.0,
            close=10.5,
            volume=100,
            provider=provider,
            feed=feed,
            source_timestamp=START + timedelta(minutes=offset + 1),
            received_at=START + timedelta(minutes=offset + 1),
            session="regular",
            is_closed=True,
            is_complete=True,
        )
        for offset in range(15)
    ]


def test_mixed_feed_is_rejected_before_deduplicating_minutes() -> None:
    rows = minutes()
    rows.append(replace(rows[0], feed="sip"))
    with pytest.raises(ValueError, match="same provider and feed"):
        aggregate_bars(rows, "15m", as_of=AS_OF)


def test_mixed_provider_is_rejected_before_aggregation() -> None:
    rows = minutes()
    rows[3] = replace(rows[3], provider="different")
    with pytest.raises(ValueError, match="same provider and feed"):
        aggregate_bars(rows, "15m", as_of=AS_OF)


def test_time_boundary_cannot_confirm_an_unclosed_source_minute() -> None:
    rows = minutes()
    rows[-1] = replace(rows[-1], is_closed=False)
    result = aggregate_bars(rows, "15m", as_of=AS_OF)
    assert len(result) == 1
    assert result[0].is_closed is False
    assert result[0].is_complete is True
    assert "PARTIAL_BAR" in result[0].quality_flags
    assert aggregate_bars(rows, "15m", as_of=AS_OF, include_forming=False) == []


def test_fifteen_rows_off_the_minute_grid_are_not_complete() -> None:
    rows = minutes()
    rows[0] = replace(
        rows[0],
        bar_start=START + timedelta(seconds=30),
        bar_end=START + timedelta(minutes=1, seconds=30),
    )
    result = aggregate_bars(rows, "15m", as_of=AS_OF)
    assert result[0].is_complete is False
    assert "MISSING_BAR" in result[0].quality_flags
    assert result[0].health.signal_permission is not SignalPermission.NORMAL


def test_unknown_feed_is_retained_as_unknown_not_a_trading_grade_fact() -> None:
    result = aggregate_bars(minutes(feed=None), "15m", as_of=AS_OF)
    assert result[0].feed is None
    assert "FEED_UNVERIFIED" in result[0].quality_flags
    assert result[0].health.signal_permission is not SignalPermission.NORMAL
