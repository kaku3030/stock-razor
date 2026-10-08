from datetime import datetime, timezone

import pandas as pd
import pytest

from data_provider.eastmoney_gm_market_data_adapter import (
    EastmoneyGMMarketDataAdapter,
    normalize_cn_symbol,
)
from data_provider.market_data_adapter import SignalPermission


NOW = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)


class FakeGM:
    def __init__(self):
        self.history_n_calls = []
        self.history_calls = []
        self.current_calls = []

    def history_n(self, **kwargs):
        self.history_n_calls.append(kwargs)
        return pd.DataFrame([
            {"symbol": "SHSE.600519", "bob": "2026-09-30 09:45", "eob": "2026-09-30 10:00",
             "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1200, "amount": 121000}
        ])

    def history(self, **kwargs):
        self.history_calls.append(kwargs)
        return self.history_n(**kwargs)

    def current(self, **kwargs):
        self.current_calls.append(kwargs)
        return [{"symbol": "SHSE.600519", "last_price": 101, "volume": 1200, "amount": 121000}]


def test_symbol_mapping_supports_stock_and_etf() -> None:
    assert normalize_cn_symbol("600519.SH") == ("600519.SH", "SHSE.600519", "stock")
    assert normalize_cn_symbol("159611.SZ") == ("159611.SZ", "SZSE.159611", "etf")
    assert normalize_cn_symbol("512730") == ("512730.SH", "SHSE.512730", "etf")


def test_history_n_normalizes_cn_timezone_and_quality_contract() -> None:
    client = FakeGM()
    adapter = EastmoneyGMMarketDataAdapter(client, now=lambda: NOW)

    bars = adapter.get_bars("600519.SH", "15m", limit=20)

    assert len(bars) == 1
    assert bars[0].symbol == "600519.SH"
    assert bars[0].bar_end.isoformat() == "2026-09-30T02:00:00+00:00"
    assert bars[0].amount == 121000
    assert bars[0].is_closed is True
    assert bars[0].health.signal_permission is SignalPermission.NORMAL
    assert client.history_n_calls[0]["symbol"] == "SHSE.600519"
    assert client.history_n_calls[0]["frequency"] == "15m"


def test_history_is_cached_without_second_provider_call() -> None:
    client = FakeGM()
    adapter = EastmoneyGMMarketDataAdapter(client, now=lambda: NOW)
    adapter.get_bars("600519.SH", "1d", limit=20)
    adapter.get_bars("600519.SH", "1d", limit=20)
    assert len(client.history_n_calls) == 1


def test_explicit_history_window_supports_60m_without_using_history_n() -> None:
    client = FakeGM()
    adapter = EastmoneyGMMarketDataAdapter(client, now=lambda: NOW)
    bars = adapter.get_bars(
        "512730.SH",
        "60m",
        start=datetime(2026, 9, 29, 1, tzinfo=timezone.utc),
        end=datetime(2026, 9, 30, 1, tzinfo=timezone.utc),
        limit=20,
    )
    assert bars[0].timeframe == "60m"
    assert bars[0].asset_type == "etf"
    assert client.history_calls[0]["frequency"] == "60m"


def test_current_without_timestamp_is_watch_only_and_never_live_ready() -> None:
    adapter = EastmoneyGMMarketDataAdapter(FakeGM(), now=lambda: NOW)
    quote = adapter.get_latest_quote("600519.SH")
    assert "MISSING_SOURCE_TIMESTAMP" in quote.quality_flags
    assert quote.health.signal_permission is SignalPermission.WATCH_ONLY


def test_end_only_daily_query_uses_bounded_history_n() -> None:
    client = FakeGM()
    adapter = EastmoneyGMMarketDataAdapter(client, now=lambda: NOW)
    adapter.get_bars("600519.SH", "1d", end=NOW, limit=20)
    assert client.history_calls == []
    assert client.history_n_calls[0]["count"] == 20
    assert client.history_n_calls[0]["end_time"] == "2026-09-30 16:00:00"
    assert "start_time" not in client.history_n_calls[0]


def test_subscription_is_explicitly_blocked() -> None:
    adapter = EastmoneyGMMarketDataAdapter(FakeGM(), now=lambda: NOW)
    with pytest.raises(NotImplementedError, match="UNKNOWN/BLOCKED"):
        adapter.subscribe(["600519.SH"])


def test_intraday_bars_mark_duplicate_and_gap_timestamps_blocked() -> None:
    class BrokenGM(FakeGM):
        def history_n(self, **kwargs):
            return pd.DataFrame([
                {"bob": "2026-09-30 09:30", "eob": "2026-09-30 09:45", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 10},
                {"bob": "2026-09-30 09:30", "eob": "2026-09-30 09:45", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 10},
                {"bob": "2026-09-30 10:15", "eob": "2026-09-30 10:30", "open": 101, "high": 102, "low": 100, "close": 101.5, "volume": 12},
            ])

    bars = EastmoneyGMMarketDataAdapter(BrokenGM(), now=lambda: NOW).get_bars(
        "600519.SH", "15m", limit=20
    )

    flags = {flag for bar in bars for flag in bar.quality_flags}
    assert {"DUPLICATE_TIMESTAMP", "MISSING_BAR"}.issubset(flags)
    assert all(bar.health is not None and bar.health.signal_permission is not SignalPermission.NORMAL for bar in bars)


def test_intraday_bars_mark_missing_ohlcv_instead_of_coercing_to_zero() -> None:
    class IncompleteGM(FakeGM):
        def history_n(self, **kwargs):
            return pd.DataFrame([
                {"bob": "2026-09-30 09:30", "eob": "2026-09-30 09:45", "open": 100, "high": 101, "low": 99, "close": 100.5},
            ])

    bars = EastmoneyGMMarketDataAdapter(IncompleteGM(), now=lambda: NOW).get_bars(
        "600519.SH", "15m", limit=20
    )

    assert "MISSING_OHLCV" in bars[0].quality_flags
    assert bars[0].health is not None
    assert bars[0].health.signal_permission is SignalPermission.BLOCKED
