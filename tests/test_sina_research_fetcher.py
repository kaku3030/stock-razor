import pandas as pd
import pytest

from data_provider.base import DataFetchError
from data_provider.sina_research_fetcher import SinaResearchFetcher


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_sina_daily_parses_and_normalizes(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        return _Response([
            {"day": "2024-01-03", "open": "10", "high": "11", "low": "9", "close": "10.5", "volume": "1200", "amount": "12600", "changepercent": "1.2"},
            {"day": "2024-01-02", "open": "9", "high": "10", "low": "8", "close": "9.8", "volume": "1000", "amount": "9800", "changepercent": "-0.5"},
        ])

    monkeypatch.setattr("data_provider.sina_research_fetcher.requests.get", fake_get)
    frame = SinaResearchFetcher().get_price("600000", frequency="1d", count=2)

    assert list(frame["date"]) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert list(frame["close"]) == [9.8, 10.5]
    assert list(frame["pct_chg"]) == [-0.5, 1.2]
    assert calls[0][1]["scale"] == 240
    assert calls[0][2] == 8.0


@pytest.mark.parametrize(
    ("frequency", "scale"),
    [("1w", 1200), ("1M", 7200), ("15m", 15)],
)
def test_sina_frequency_scale(monkeypatch, frequency, scale):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _Response([])

    monkeypatch.setattr("data_provider.sina_research_fetcher.requests.get", fake_get)
    SinaResearchFetcher().get_price("000001", frequency=frequency, count=1)
    assert calls[0]["scale"] == scale


@pytest.mark.parametrize(
    "kwargs",
    [
        {"stock_code": "AAPL"},
        {"stock_code": "600000", "frequency": "2d"},
        {"stock_code": "600000", "count": 0},
    ],
)
def test_sina_rejects_invalid_requests(kwargs):
    with pytest.raises(DataFetchError):
        SinaResearchFetcher().get_price(**kwargs)


def test_sina_raw_data_applies_date_window(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _Response([
            {"day": "2024-01-01", "close": "1", "volume": "10"},
            {"day": "2024-01-02", "close": "2", "volume": "20"},
            {"day": "2024-01-03", "close": "3", "volume": "30"},
        ])

    monkeypatch.setattr("data_provider.sina_research_fetcher.requests.get", fake_get)
    frame = SinaResearchFetcher()._fetch_raw_data("600000", "2024-01-02", "2024-01-02")
    assert list(frame["date"]) == [pd.Timestamp("2024-01-02")]


def test_sina_is_registered_for_cn_daily_market():
    from data_provider.base import DataFetcherManager

    support = DataFetcherManager._DAILY_MARKET_FETCHER_SUPPORT
    assert support["SinaResearchFetcher"] == {"cn"}


def test_sina_transport_failure_is_data_fetch_error(monkeypatch):
    import requests

    def failed_get(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("data_provider.sina_research_fetcher.requests.get", failed_get)
    with pytest.raises(DataFetchError, match="Sina request failed"):
        SinaResearchFetcher().get_price("600000")
