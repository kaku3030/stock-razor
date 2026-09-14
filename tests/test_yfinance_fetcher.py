import sys
import types

import pandas as pd
import pytest

from data_provider.base import DataFetchError
from data_provider.yfinance_fetcher import YfinanceFetcher


def test_yfinance_empty_download_is_data_fetch_error(monkeypatch):
    fake = types.SimpleNamespace(download=lambda **kwargs: pd.DataFrame())
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    with pytest.raises(DataFetchError, match="未查询到"):
        YfinanceFetcher()._fetch_raw_data("AAPL", "2024-01-01", "2024-01-05")


def test_yfinance_transport_failure_is_data_fetch_error(monkeypatch):
    def failed_download(**kwargs):
        raise TimeoutError("offline")

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=failed_download))

    with pytest.raises(DataFetchError, match="获取数据失败"):
        YfinanceFetcher()._fetch_raw_data("AAPL", "2024-01-01", "2024-01-05")
