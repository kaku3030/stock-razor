from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from data_provider.market_bar_builder import aggregate_bars
from data_provider.market_data_adapter import Bar, SignalPermission


CN = ZoneInfo("Asia/Shanghai")
US = ZoneInfo("America/New_York")


def minute_bar(minute: datetime, *, close: float = 10, received_offset: int = 0) -> Bar:
    return Bar(
        symbol="600519",
        market="cn",
        asset_type="stock",
        timeframe="1m",
        bar_start=minute,
        bar_end=minute + timedelta(minutes=1),
        open=close - 0.1,
        high=close + 0.2,
        low=close - 0.2,
        close=close,
        volume=100,
        amount=close * 100,
        provider="fake",
        source_timestamp=minute + timedelta(minutes=1),
        received_at=minute + timedelta(minutes=1, seconds=received_offset),
        session="regular",
        is_closed=True,
        is_complete=True,
    )


def us_minute_bar(minute: datetime, *, closed: bool = True) -> Bar:
    return Bar(
        symbol="US.AMD",
        market="us",
        asset_type="stock",
        timeframe="1m",
        bar_start=minute,
        bar_end=minute + timedelta(minutes=1),
        open=100,
        high=101,
        low=99,
        close=100,
        volume=10,
        amount=1000,
        provider="futu",
        feed="opend",
        source_timestamp=minute + timedelta(minutes=1),
        received_at=minute + timedelta(minutes=1),
        session="regular",
        is_closed=closed,
        is_complete=closed,
    )


def test_builds_closed_complete_15m_bar() -> None:
    start = datetime(2026, 9, 1, 9, 30, tzinfo=CN)
    source = [minute_bar(start + timedelta(minutes=i), close=10 + i / 10) for i in range(15)]

    result = aggregate_bars(source, "15m", as_of=datetime(2026, 9, 1, 9, 45, tzinfo=CN))

    assert len(result) == 1
    assert result[0].bar_start == start
    assert result[0].bar_end == datetime(2026, 9, 1, 9, 45, tzinfo=CN)
    assert result[0].is_closed is True
    assert result[0].is_complete is True
    assert result[0].volume == 1500
    assert result[0].close == 11.4


def test_a_share_hour_bars_do_not_cross_lunch_break() -> None:
    morning = datetime(2026, 9, 1, 10, 30, tzinfo=CN)
    afternoon = datetime(2026, 9, 1, 13, 0, tzinfo=CN)
    source = [minute_bar(morning + timedelta(minutes=i)) for i in range(60)]
    source += [minute_bar(afternoon + timedelta(minutes=i)) for i in range(60)]

    result = aggregate_bars(source, "1h", as_of=datetime(2026, 9, 1, 14, 0, tzinfo=CN))

    assert [(bar.bar_start.hour, bar.bar_end.hour) for bar in result] == [(10, 11), (13, 14)]
    assert all(bar.is_complete for bar in result)


def test_missing_minutes_degrade_signal_permission() -> None:
    start = datetime(2026, 9, 1, 9, 30, tzinfo=CN)
    source = [minute_bar(start + timedelta(minutes=i)) for i in range(10)]

    result = aggregate_bars(source, "15m", as_of=datetime(2026, 9, 1, 9, 45, tzinfo=CN))

    assert result[0].is_complete is False
    assert "MISSING_BAR" in result[0].quality_flags
    assert result[0].health.signal_permission is not SignalPermission.NORMAL


def test_forming_bar_is_marked_and_can_be_excluded() -> None:
    start = datetime(2026, 9, 1, 9, 30, tzinfo=CN)
    source = [minute_bar(start + timedelta(minutes=i)) for i in range(5)]
    as_of = datetime(2026, 9, 1, 9, 35, tzinfo=CN)

    included = aggregate_bars(source, "15m", as_of=as_of)
    excluded = aggregate_bars(source, "15m", as_of=as_of, include_forming=False)

    assert included[0].is_closed is False
    assert "PARTIAL_BAR" in included[0].quality_flags
    assert excluded == []


def test_later_provider_correction_replaces_same_minute() -> None:
    start = datetime(2026, 9, 1, 9, 30, tzinfo=CN)
    source = [minute_bar(start + timedelta(minutes=i)) for i in range(15)]
    source.append(minute_bar(start + timedelta(minutes=14), close=20, received_offset=30))

    result = aggregate_bars(source, "15m", as_of=datetime(2026, 9, 1, 9, 45, tzinfo=CN))

    assert result[0].close == 20
    assert result[0].volume == 1500


def test_mixed_market_or_non_minute_input_is_rejected() -> None:
    start = datetime(2026, 9, 1, 9, 30, tzinfo=CN)
    source = [minute_bar(start)]
    source[0] = Bar(**{**source[0].__dict__, "timeframe": "15m"})

    try:
        aggregate_bars(source, "15m", as_of=datetime.now(timezone.utc))
    except ValueError as exc:
        assert "same market" in str(exc)
    else:
        raise AssertionError("non-minute input must be rejected")


def test_us_15m_and_1h_require_closed_complete_source_grid() -> None:
    start = datetime(2026, 10, 5, 9, 30, tzinfo=US)
    forming_source = [
        us_minute_bar(start + timedelta(minutes=i), closed=i != 59)
        for i in range(60)
    ]

    forming = aggregate_bars(
        forming_source,
        "1h",
        as_of=datetime(2026, 10, 5, 10, 30, tzinfo=US),
        include_forming=False,
    )
    assert forming == []

    closed_source = [us_minute_bar(start + timedelta(minutes=i)) for i in range(60)]
    fifteen = aggregate_bars(
        closed_source,
        "15m",
        as_of=datetime(2026, 10, 5, 10, 30, tzinfo=US),
        include_forming=False,
    )
    hourly = aggregate_bars(
        closed_source,
        "1h",
        as_of=datetime(2026, 10, 5, 10, 30, tzinfo=US),
        include_forming=False,
    )
    assert len(fifteen) == 4
    assert len(hourly) == 1
    assert all(bar.is_closed and bar.is_complete for bar in [*fifteen, *hourly])
