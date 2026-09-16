"""Provider-independent, credential-free regressions for price/time evidence."""

from datetime import datetime, timezone

from data_provider.alpaca_market_data_adapter import AlpacaMarketDataAdapter
from data_provider.market_data_adapter import SignalPermission


BAR = {"t": "2026-09-17T14:29:00Z", "o": 200, "h": 201, "l": 199, "c": 200.5, "v": 100}


class FakeRest:
    def __init__(self, *, bar=None, quote=None):
        self.bar = BAR if bar is None else bar
        self.quote = {"t": "2026-09-17T14:29:59Z", "bp": 200.4, "ap": 200.6} if quote is None else quote

    def get_latest_bar(self, symbol, *, feed):
        return self.bar

    def get_latest_quote(self, symbol, *, feed):
        return self.quote


def test_bar_close_price_uses_bar_end_not_newer_bbo_timestamp() -> None:
    latest_bbo = {"t": "2026-09-17T14:31:00Z", "bp": 205, "ap": 206}
    adapter = AlpacaMarketDataAdapter(
        FakeRest(quote=latest_bbo), now=lambda: datetime(2026, 9, 17, 14, 32, tzinfo=timezone.utc)
    )
    quote = adapter.get_latest_quote("NVDA")
    assert quote.price == 200.5
    assert quote.source_timestamp == datetime(2026, 9, 17, 14, 30, tzinfo=timezone.utc)
    assert quote.bid is None and quote.ask is None
    assert "BBO_TIME_NOT_COMPARABLE" in quote.quality_flags


def test_stale_bar_price_is_not_relabelled_fresh_by_new_quote() -> None:
    latest_bbo = {"t": "2026-09-17T16:00:00Z", "bp": 205, "ap": 206}
    adapter = AlpacaMarketDataAdapter(
        FakeRest(quote=latest_bbo), now=lambda: datetime(2026, 9, 17, 16, 1, tzinfo=timezone.utc)
    )
    quote = adapter.get_latest_quote("NVDA")
    assert quote.source_timestamp == datetime(2026, 9, 17, 14, 30, tzinfo=timezone.utc)
    assert "STALE" in quote.quality_flags
    assert quote.health.signal_permission is not SignalPermission.NORMAL


def test_missing_price_timestamp_does_not_borrow_bbo_timestamp() -> None:
    adapter = AlpacaMarketDataAdapter(
        FakeRest(bar={"c": 200.5, "v": 100}),
        now=lambda: datetime(2026, 9, 17, 14, 32, tzinfo=timezone.utc),
    )
    quote = adapter.get_latest_quote("NVDA")
    assert "MISSING_SOURCE_TIMESTAMP" in quote.quality_flags
    assert quote.bid is None and quote.ask is None
    assert quote.health.signal_permission is not SignalPermission.NORMAL


def test_delayed_feed_never_silently_becomes_unlabelled_realtime() -> None:
    adapter = AlpacaMarketDataAdapter(
        FakeRest(), feed="delayed_sip",
        now=lambda: datetime(2026, 9, 17, 14, 31, tzinfo=timezone.utc),
    )
    quote = adapter.get_latest_quote("NVDA")
    assert quote.feed == "delayed_sip"
    assert "DELAYED_FEED" in quote.quality_flags


def test_live_stream_bar_can_be_closed_but_stale() -> None:
    adapter = AlpacaMarketDataAdapter(
        FakeRest(), now=lambda: datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)
    )
    bar = adapter._normalize_bar("NVDA", BAR, live=True)
    assert bar.is_closed is True
    assert "STALE" in bar.quality_flags
    assert bar.health.signal_permission is not SignalPermission.NORMAL
