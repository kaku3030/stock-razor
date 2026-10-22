from datetime import datetime, timezone

import pandas as pd
import pytest

from data_provider.stockdata_hub_historical_adapter import CN_ZONE, StockDataHubHistoricalAdapter


class _Fetcher:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def fetch_intraday(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.frame, None, args[0]


class _DailyFetcher:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def get_daily_data(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.frame


def _frame():
    return pd.DataFrame([
        {"datetime": "2026-10-20 09:30:00", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100, "amount": 1000},
        {"datetime": "2026-10-20 09:45:00", "open": 10.5, "high": 12, "low": 10, "close": 11, "volume": 120, "amount": 1320},
    ])


def _daily_frame():
    return pd.DataFrame([
        {"date": "2026-10-12", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
        {"date": "2026-10-13", "open": 11, "high": 13, "low": 10, "close": 12, "volume": 120},
        {"date": "2026-10-19", "open": 12, "high": 14, "low": 11, "close": 13, "volume": 140},
    ])


def test_fetches_15m_with_cache_and_preserves_cn_timezone():
    fetcher = _Fetcher(_frame())
    adapter = StockDataHubHistoricalAdapter(
        fetcher, now=lambda: datetime(2026, 10, 20, 2, 0, tzinfo=timezone.utc)
    )

    bars = adapter.get_bars("600519", "15m", limit=2)

    assert len(bars) == 2
    assert bars[0].bar_start.tzinfo == CN_ZONE
    assert bars[0].bar_end.hour == 9
    assert bars[0].is_closed is True
    assert "TIMESTAMP_SEMANTICS_UNVERIFIED" in bars[0].quality_flags
    assert bars[0].health.signal_permission.value == "blocked"
    assert fetcher.calls[0][1] == {"period": "15m", "days": 30, "count": 2, "use_cache": True}


@pytest.mark.parametrize(("timeframe", "period"), [("15m", "15m"), ("1h", "60m")])
def test_long_intraday_history_requests_full_range_from_2016(timeframe, period):
    frame = pd.DataFrame([
        {"datetime": "2016-07-04 09:30:00", "open": 8, "high": 9, "low": 7, "close": 8.5, "volume": 100},
        {"datetime": "2026-10-21 14:00:00", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 120},
    ])
    fetcher = _Fetcher(frame)
    adapter = StockDataHubHistoricalAdapter(
        fetcher, now=lambda: datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)
    )

    bars = adapter.get_bars(
        "000001", timeframe,
        start=datetime(2016, 7, 4, tzinfo=CN_ZONE),
        end=datetime(2026, 10, 22, tzinfo=CN_ZONE),
    )

    assert [bar.bar_start.date().isoformat() for bar in bars] == ["2016-07-04", "2026-10-21"]
    assert fetcher.calls[0][1]["period"] == period
    assert fetcher.calls[0][1]["days"] >= 3760
    assert fetcher.calls[0][1]["use_cache"] is False


def test_one_hour_maps_to_stockdata_hub_60m():
    fetcher = _Fetcher(_frame())
    StockDataHubHistoricalAdapter(fetcher).get_bars("000001", "1h")
    assert fetcher.calls[0][1]["period"] == "60m"


def test_unsupported_period_and_invalid_ohlcv_fail_closed():
    with pytest.raises(ValueError, match="only 15m, 1h, 1d, 1w and 1y"):
        StockDataHubHistoricalAdapter(_Fetcher(_frame())).get_bars("600519", "5m")

    invalid = _frame()
    invalid.loc[0, "low"] = 20
    with pytest.raises(ValueError, match="invalid OHLCV"):
        StockDataHubHistoricalAdapter(_Fetcher(invalid)).get_bars("600519", "15m")


def test_daily_uses_existing_daily_fetcher_and_closes_at_cn_market_close():
    fetcher = _DailyFetcher(_daily_frame())
    adapter = StockDataHubHistoricalAdapter(
        daily_fetcher=fetcher,
        now=lambda: datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc),
    )

    bars = adapter.get_bars("600519", "1d", limit=2)

    assert [bar.bar_start.date().isoformat() for bar in bars] == ["2026-10-13", "2026-10-19"]
    assert bars[0].bar_end.hour == 15
    assert bars[0].bar_end.date().isoformat() == "2026-10-13"
    assert all(bar.is_closed for bar in bars)
    assert fetcher.calls[0][1]["days"] >= 14


def test_daily_bar_closes_at_1500_on_its_own_trading_date():
    fetcher = _DailyFetcher(pd.DataFrame([
        {"date": "2026-10-22", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
    ]))
    before_close = StockDataHubHistoricalAdapter(
        daily_fetcher=fetcher,
        now=lambda: datetime(2026, 10, 22, 6, 59, tzinfo=timezone.utc),
    ).get_bars("000001", "1d", limit=1)[0]
    after_close = StockDataHubHistoricalAdapter(
        daily_fetcher=fetcher,
        now=lambda: datetime(2026, 10, 22, 7, 0, tzinfo=timezone.utc),
    ).get_bars("000001", "1d", limit=1)[0]

    assert before_close.bar_end.isoformat() == "2026-10-22T15:00:00+08:00"
    assert before_close.is_closed is False
    assert after_close.is_closed is True


def test_weekly_aggregates_trading_days_without_cross_week_leakage():
    adapter = StockDataHubHistoricalAdapter(daily_fetcher=_DailyFetcher(_daily_frame()))

    bars = adapter.get_bars("000001", "1w")

    assert [bar.bar_start.date().isoformat() for bar in bars] == ["2026-10-12", "2026-10-19"]
    assert bars[0].open == 10
    assert bars[0].high == 13
    assert bars[0].low == 9
    assert bars[0].close == 12
    assert bars[0].volume == 220
    assert bars[-1].bar_end.date().isoformat() == "2026-10-23"
    assert bars[-1].bar_end.hour == 15


def test_yearly_aggregates_calendar_years():
    frame = _daily_frame()
    frame.loc[len(frame)] = {"date": "2025-12-31", "open": 8, "high": 9, "low": 7, "close": 8.5, "volume": 80}
    adapter = StockDataHubHistoricalAdapter(daily_fetcher=_DailyFetcher(frame))

    bars = adapter.get_bars("000001", "1y")

    assert [bar.bar_start.date().isoformat() for bar in bars] == ["2025-01-01", "2026-01-01"]
    assert bars[0].open == 8
    assert bars[0].close == 8.5
    assert bars[0].bar_end.date().isoformat() == "2025-12-31"
    assert bars[0].bar_end.hour == 15
