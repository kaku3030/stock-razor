from datetime import datetime, timezone

import pytest

from data_provider.tickflow_ws_research_observer import (
    TickFlowWebSocketResearchObserver,
    attach_tickflow_stream,
)


SYMBOLS = ("159611.SZ", "518880.SH")


class FakeStream:
    def __init__(self):
        self.quote_handler = None
        self.error_handler = None
        self.subscriptions = []
        self.connected = False

    def on_quotes(self, handler):
        self.quote_handler = handler

    def on_error(self, handler):
        self.error_handler = handler

    def subscribe(self, channel, symbols):
        self.subscriptions.append((channel, symbols))

    def connect(self, *, block):
        assert block is False
        self.connected = True

    def close(self):
        self.connected = False


class FakeClient:
    def __init__(self):
        self.stream = FakeStream()


def test_official_stream_usage_is_sanitized_and_not_qualified():
    clock = iter((1776754800000, 1776754801700, 1776754802800))
    observer = TickFlowWebSocketResearchObserver(SYMBOLS, now_ms=lambda: next(clock))
    client = FakeClient()
    attached = attach_tickflow_stream(client, SYMBOLS)
    assert attached.subscription_call == "PASS"
    assert attached.connection_call == "PASS"
    assert client.stream.subscriptions == [("quotes", sorted(SYMBOLS))]

    attached._now_ms = lambda: next(clock)
    client.stream.quote_handler([{"symbol": SYMBOLS[0], "timestamp": 1776754800000, "last_price": 999}])
    client.stream.quote_handler([{"symbol": SYMBOLS[0], "timestamp": 1776754801000, "last_price": 999}])
    client.stream.quote_handler([{"symbol": SYMBOLS[0], "timestamp": 1776754801000}])
    client.stream.error_handler("api_key=DO_NOT_LEAK")
    result = attached.summary(observed_at_utc=datetime(2026, 4, 21, tzinfo=timezone.utc))

    assert result["initial_snapshot_candidates"] == 1
    assert result["post_initial_update_candidates"] == 1
    assert result["duplicate_timestamp_events"] == 1
    assert result["error_callbacks"] == 1
    assert result["subscription_ack"] == "NOT_OBSERVABLE_VIA_OFFICIAL_SYNC_SDK"
    assert result["continuous_feed_qualified"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert "999" not in str(result)
    assert "DO_NOT_LEAK" not in str(result)


@pytest.mark.parametrize("symbols", [(), ("AAPL.US",), ("159611.SZ",) * 2])
def test_symbol_scope_fails_closed(symbols):
    with pytest.raises(ValueError):
        TickFlowWebSocketResearchObserver(symbols)
