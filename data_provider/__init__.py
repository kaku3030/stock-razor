# -*- coding: utf-8 -*-
"""Provider package namespace with lazy compatibility exports.

Importing a provider submodule must not eagerly import every optional provider
and its third-party dependencies. Legacy package-root imports remain available
through PEP 562 lazy attribute resolution.
"""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "BaseFetcher": (".base", "BaseFetcher"),
    "DataFetcherManager": (".base", "DataFetcherManager"),
    "SinaResearchFetcher": (".sina_research_fetcher", "SinaResearchFetcher"),
    "EfinanceFetcher": (".efinance_fetcher", "EfinanceFetcher"),
    "TencentFetcher": (".tencent_fetcher", "TencentFetcher"),
    "AkshareFetcher": (".akshare_fetcher", "AkshareFetcher"),
    "TushareFetcher": (".tushare_fetcher", "TushareFetcher"),
    "PytdxFetcher": (".pytdx_fetcher", "PytdxFetcher"),
    "BaostockFetcher": (".baostock_fetcher", "BaostockFetcher"),
    "YfinanceFetcher": (".yfinance_fetcher", "YfinanceFetcher"),
    "LongbridgeFetcher": (".longbridge_fetcher", "LongbridgeFetcher"),
    "FinnhubFetcher": (".finnhub_fetcher", "FinnhubFetcher"),
    "AlphaVantageFetcher": (".alphavantage_fetcher", "AlphaVantageFetcher"),
    "ActualContinuousMapping": (".futures_provider", "ActualContinuousMapping"),
    "FUTURES_INSTRUMENTS": (".futures_provider", "FUTURES_INSTRUMENTS"),
    "YahooFuturesHistoryProvider": (".futures_provider", "YahooFuturesHistoryProvider"),
    "YahooFuturesProviderBinding": (".futures_provider", "YahooFuturesProviderBinding"),
    "should_roll": (".futures_provider", "should_roll"),
    "is_us_index_code": (".us_index_mapping", "is_us_index_code"),
    "is_us_stock_code": (".us_index_mapping", "is_us_stock_code"),
    "get_us_index_yf_symbol": (".us_index_mapping", "get_us_index_yf_symbol"),
    "US_INDEX_MAPPING": (".us_index_mapping", "US_INDEX_MAPPING"),
    "is_hk_stock_code": (".akshare_fetcher", "is_hk_stock_code"),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
