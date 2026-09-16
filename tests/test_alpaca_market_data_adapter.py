import asyncio
from datetime import datetime, timezone

import pytest

from data_provider.alpaca_market_data_adapter import AlpacaMarketDataAdapter, AlpacaRestMarketDataClient


NOW = datetime(2026, 9, 1, 14, 31, tzinfo=timezone.utc)
BAR = {"t": "2026-09-01T14:29:00Z", "o": 180, "h": 182, "l": 179, "c": 181, "v": 1000, "vw": 180.5}


class FakeRest:
    def __init__(self):
        self.bars = [BAR]
        self.latest_bar = BAR
        self.latest_quote = {"t": "2026-09-01T14:29:59Z", "bp": 180.9, "ap": 181.1}

    def get_bars(self, symbol, **kwargs):
        self.bars_call = (symbol, kwargs)
        return self.bars

    def get_latest_bar(self, symbol, *, feed):
        return self.latest_bar

    def get_latest_quote(self, symbol, *, feed):
        return self.latest_quote


class FakeStream:
    def subscribe_bars(self, handler, *symbols):
        self.bar_subscription = (handler, symbols)

    def subscribe_updated_bars(self, handler, *symbols):
        self.updated_subscription = (handler, symbols)


def test_alpaca_rest_history_requests_latest_page() -> None:
    client = AlpacaRestMarketDataClient("key", "secret")
    captured = {}

    def fake_get(path, params):
        captured.update({"path": path, "params": params})
        return {"bars": []}

    client._get = fake_get
    client.get_bars(
        "NVDA",
        start="2026-08-01T00:00:00+00:00",
        end="2026-09-01T00:00:00+00:00",
        limit=3000,
        feed="iex",
    )

    assert captured["params"]["sort"] == "desc"
    assert captured["params"]["start"] == "2026-08-01T00:00:00+00:00"


def test_alpaca_history_keeps_feed_timestamp_and_vwap() -> None:
    rest = FakeRest()
    adapter = AlpacaMarketDataAdapter(rest, feed="iex", now=lambda: NOW)

    bars = adapter.get_bars("nvda", "1m", limit=20)

    assert bars[0].symbol == "NVDA"
    assert bars[0].feed == "iex"
    assert bars[0].bar_start.isoformat() == "2026-09-01T14:29:00+00:00"
    assert bars[0].vwap == 180.5
    assert rest.bars_call[1]["limit"] == 20


def test_alpaca_latest_quote_combines_latest_bar_and_bbo() -> None:
    adapter = AlpacaMarketDataAdapter(FakeRest(), feed="sip", now=lambda: NOW)

    quote = adapter.get_latest_quote("NVDA")

    assert quote.price == 181
    assert quote.bid == 180.9
    assert quote.ask == 181.1
    assert quote.feed == "sip"
    assert quote.session == "regular"


def test_alpaca_subscribes_to_bars_and_updated_bars() -> None:
    stream = FakeStream()
    received = []
    adapter = AlpacaMarketDataAdapter(FakeRest(), stream_client=stream, feed="iex", now=lambda: NOW)

    adapter.subscribe(["nvda"], callback=received.append)
    asyncio.run(stream.bar_subscription[0]({"T": "b", "S": "NVDA", **BAR}))
    asyncio.run(stream.updated_subscription[0]({"T": "u", "S": "NVDA", **BAR}))

    assert stream.bar_subscription[1] == ("NVDA",)
    assert stream.updated_subscription[1] == ("NVDA",)
    assert len(received) == 2
    assert "UPDATED_BAR" not in received[0].quality_flags
    assert "UPDATED_BAR" in received[1].quality_flags
    assert received[0].bar_start == received[1].bar_start


def test_alpaca_rejects_unknown_feed_and_fake_higher_timeframe() -> None:
    with pytest.raises(ValueError, match="unsupported Alpaca feed"):
        AlpacaMarketDataAdapter(FakeRest(), feed="magic")
    adapter = AlpacaMarketDataAdapter(FakeRest(), feed="iex", now=lambda: NOW)
    with pytest.raises(NotImplementedError, match="raw 1m"):
        adapter.get_bars("NVDA", "15m")
