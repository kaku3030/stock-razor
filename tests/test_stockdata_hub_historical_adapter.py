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


def _frame():
    return pd.DataFrame([
        {"datetime": "2026-10-20 09:30:00", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100, "amount": 1000},
        {"datetime": "2026-10-20 09:45:00", "open": 10.5, "high": 12, "low": 10, "close": 11, "volume": 120, "amount": 1320},
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


def test_one_hour_maps_to_stockdata_hub_60m():
    fetcher = _Fetcher(_frame())
    StockDataHubHistoricalAdapter(fetcher).get_bars("000001", "1h")
    assert fetcher.calls[0][1]["period"] == "60m"


def test_unsupported_period_and_invalid_ohlcv_fail_closed():
    with pytest.raises(ValueError, match="only 15m and 1h"):
        StockDataHubHistoricalAdapter(_Fetcher(_frame())).get_bars("600519", "1d")

    invalid = _frame()
    invalid.loc[0, "low"] = 20
    with pytest.raises(ValueError, match="invalid OHLCV"):
        StockDataHubHistoricalAdapter(_Fetcher(invalid)).get_bars("600519", "15m")
