# -*- coding: utf-8 -*-
"""Sina K-line adapter derived from the public Ashare interface contract.

This is an independent implementation of the documented Sina endpoint shape;
the upstream Ashare repository is referenced for compatibility, not copied.
Research/fallback use only; never a production execution feed.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
import requests

from .base import BaseFetcher, DataFetchError, normalize_stock_code

_SINA_KLINE_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
_TIMEOUT_SECONDS = 8
_ALLOWED_FREQUENCIES = {"1m", "5m", "15m", "30m", "60m", "1d", "1w", "1M"}


def _sina_symbol(stock_code: str) -> str:
    code = normalize_stock_code(stock_code).upper()
    if not code.isdigit() or len(code) != 6:
        raise DataFetchError(f"SinaResearchFetcher unsupported stock code: {stock_code}")
    return ("sh" if code.startswith(("5", "6", "9")) else "sz") + code


class SinaResearchFetcher(BaseFetcher):
    """Read-only Sina K-line source for Radar research and fallback capture."""

    name = "SinaResearchFetcher"
    priority = 6
    allow_empty_daily_data = True

    def get_price(
        self,
        stock_code: str,
        *,
        frequency: str = "1d",
        count: int = 240,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        if frequency not in _ALLOWED_FREQUENCIES:
            raise DataFetchError(f"unsupported frequency: {frequency}")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0 or count > 5000:
            raise DataFetchError("count must be an integer between 1 and 5000")
        symbol = _sina_symbol(stock_code)
        scale = {"1d": 240, "1w": 1200, "1M": 7200}.get(frequency, int(frequency[:-1]))
        params = {"symbol": symbol, "scale": scale, "ma": 5, "datalen": count}
        response = requests.get(
            _SINA_KLINE_URL,
            params=params,
            headers={"User-Agent": "stock-razor-research/0.1", "Accept": "application/json"},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise DataFetchError(f"Sina returned invalid payload for {stock_code}")
        rows = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            rows.append({
                "date": item.get("day"),
                "open": item.get("open"),
                "high": item.get("high"),
                "low": item.get("low"),
                "close": item.get("close"),
                "volume": item.get("volume"),
                "amount": item.get("amount"),
                "pct_chg": item.get("changepercent"),
            })
        frame = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"])
        if frame.empty:
            return frame
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        for column in ["open", "high", "low", "close", "volume", "amount", "pct_chg"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["date", "close", "volume"]).sort_values("date")
        if end_date:
            frame = frame[frame["date"] <= pd.Timestamp(end_date)]
        return frame.reset_index(drop=True)

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        frame = self.get_price(stock_code, frequency="1d", count=800, end_date=end_date)
        if frame.empty:
            return frame
        return frame[(frame["date"] >= pd.Timestamp(start_date)) & (frame["date"] <= pd.Timestamp(end_date))]

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        normalized = df.copy()
        for column in ("date", "open", "high", "low", "close", "volume", "amount", "pct_chg"):
            if column not in normalized:
                normalized[column] = pd.NA
        return normalized[["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]]
