"""Offline regressions: aggregation must not upgrade delayed/history to realtime."""

from datetime import datetime, timedelta, timezone

from data_provider.alpaca_market_data_adapter import AlpacaMarketDataAdapter
from data_provider.market_bar_builder import aggregate_bars
from data_provider.market_data_adapter import SignalPermission


START = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 17, 14, 20, tzinfo=timezone.utc)


class FakeRest:
    def get_bars(self, symbol, **kwargs):
        return [
            {
                "t": (START + timedelta(minutes=i)).isoformat(),
                "o": 200, "h": 201, "l": 199, "c": 200.5, "v": 100,
            }
            for i in range(15)
        ]

    def get_latest_bar(self, symbol, *, feed):
        return {"t": "2026-09-17T14:18:00Z", "c": 200.5, "v": 100}

    def get_latest_quote(self, symbol, *, feed):
        return {"t": "2026-09-17T14:19:00Z", "bp": 200.4, "ap": 200.6}


def test_delayed_snapshot_remains_non_realtime_even_with_recent_bar() -> None:
    adapter = AlpacaMarketDataAdapter(FakeRest(), feed="delayed_sip", now=lambda: NOW)
    quote = adapter.get_latest_quote("NVDA")
    assert quote.feed == "delayed_sip"
    assert "DELAYED_FEED" in quote.quality_flags
    assert quote.health.signal_permission is not SignalPermission.NORMAL


def test_historical_bar_and_derived_fifteen_minutes_remain_non_realtime() -> None:
    adapter = AlpacaMarketDataAdapter(FakeRest(), feed="iex", now=lambda: NOW)
    one_minute = adapter.get_bars("NVDA", "1m", limit=15)
    assert len(one_minute) == 15
    assert all("HISTORICAL_QUERY" in bar.quality_flags for bar in one_minute)
    assert all(bar.health.signal_permission is not SignalPermission.NORMAL for bar in one_minute)
    aggregated = aggregate_bars(one_minute, "15m", as_of=NOW)
    assert len(aggregated) == 1
    assert aggregated[0].is_closed and aggregated[0].is_complete
    assert "HISTORICAL_QUERY" in aggregated[0].quality_flags
    assert aggregated[0].health.signal_permission is not SignalPermission.NORMAL


def test_delayed_feed_history_and_aggregate_stay_non_realtime() -> None:
    adapter = AlpacaMarketDataAdapter(FakeRest(), feed="delayed_sip", now=lambda: NOW)
    one_minute = adapter.get_bars("NVDA", "1m", limit=15)
    assert all("DELAYED_FEED" in bar.quality_flags for bar in one_minute)
    aggregated = aggregate_bars(one_minute, "15m", as_of=NOW)
    assert aggregated[0].feed == "delayed_sip"
    assert "DELAYED_FEED" in aggregated[0].quality_flags
    assert aggregated[0].health.signal_permission is not SignalPermission.NORMAL


def test_delayed_live_minute_cannot_gain_normal_permission() -> None:
    adapter = AlpacaMarketDataAdapter(FakeRest(), feed="delayed_sip", now=lambda: NOW)
    live_bar = adapter._normalize_bar(
        "NVDA", {"t": "2026-09-17T14:18:00Z", "o": 200, "h": 201,
                 "l": 199, "c": 200.5, "v": 100}, live=True,
    )
    assert "DELAYED_FEED" in live_bar.quality_flags
    assert live_bar.health.signal_permission is not SignalPermission.NORMAL
