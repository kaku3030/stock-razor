# -*- coding: utf-8 -*-
"""Read-only A-share historical intraday adapter backed by stockdata-hub."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .market_data_adapter import Bar, BarCallback, MarketDataAdapter, MarketDataHealth, Quote, evaluate_health

CN_ZONE = ZoneInfo("Asia/Shanghai")
_PERIODS = {"15m": ("15m", 15), "1h": ("60m", 60)}


class StockDataHubHistoricalAdapter(MarketDataAdapter):
    """Bounded, read-only 15m/1h A-share history for research callers."""

    def __init__(self, fetcher: Optional[object] = None, *, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._fetcher = fetcher
        self._now = now
        self._last_health = evaluate_health(
            freshness=0, completeness=0, timestamp=0, provider=0, continuity=0,
            cross_check=0, quality_flags=("NOT_OBSERVED",),
        )

    def _get_fetcher(self) -> object:
        if self._fetcher is None:
            try:
                from stockdata_hub import StockDataFetcher
            except ImportError as exc:
                raise RuntimeError("stockdata-hub is required for the CN historical adapter") from exc
            self._fetcher = StockDataFetcher(enable_name_resolution=False)
        return self._fetcher

    def get_latest_quote(self, symbol: str) -> Quote:
        raise NotImplementedError("historical adapter does not provide quotes")

    def get_bars(self, symbol: str, timeframe: str, start: Optional[datetime] = None,
                 end: Optional[datetime] = None, limit: Optional[int] = None) -> list[Bar]:
        period_info = _PERIODS.get(timeframe)
        if period_info is None:
            raise ValueError("stockdata-hub historical adapter supports only 15m and 1h")
        period, minutes = period_info
        if not symbol.isdigit() or len(symbol) != 6:
            raise ValueError(f"unsupported A-share symbol: {symbol}")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
            raise ValueError("limit must be a positive integer")
        start_cn = _as_cn(start) if start else None
        end_cn = _as_cn(end) if end else None
        frame, reason, _ = self._get_fetcher().fetch_intraday(
            symbol, period=period, days=_request_days(start_cn, end_cn),
            count=limit, use_cache=True,
        )
        if frame is None or frame.empty:
            raise LookupError(reason or f"no historical bars for {symbol}")
        return self._normalize_bars(symbol, timeframe, minutes, frame, start_cn, end_cn)

    def _normalize_bars(self, symbol: str, timeframe: str, minutes: int, frame: pd.DataFrame,
                        start: Optional[datetime], end: Optional[datetime]) -> list[Bar]:
        required = {"datetime", "open", "high", "low", "close", "volume"}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"stockdata-hub result missing columns: {sorted(missing)}")
        work = frame.copy()
        work["datetime"] = pd.to_datetime(work["datetime"], errors="coerce")
        work = work.dropna(subset=list(required)).sort_values("datetime")
        work = work.drop_duplicates(subset=["datetime"], keep="last")
        if start:
            work = work[work["datetime"] >= start.replace(tzinfo=None)]
        if end:
            work = work[work["datetime"] < end.replace(tzinfo=None)]
        received_at = _as_utc(self._now())
        result: list[Bar] = []
        for _, row in work.iterrows():
            bar_start = _as_cn(pd.Timestamp(row["datetime"]).to_pydatetime())
            bar_end = bar_start + timedelta(minutes=minutes)
            values = [float(row[name]) for name in ("open", "high", "low", "close", "volume")]
            if not all(np.isfinite(value) for value in values):
                raise ValueError(f"non-finite OHLCV returned for {symbol} at {bar_start}")
            open_, high, low, close, volume = values
            if low > min(open_, close) or high < max(open_, close) or volume < 0:
                raise ValueError(f"invalid OHLCV returned for {symbol} at {bar_start}")
            closed = received_at >= bar_end.astimezone(timezone.utc)
            flags = ("NOT_CROSS_CHECKED", "TIMESTAMP_SEMANTICS_UNVERIFIED")
            health = evaluate_health(
                freshness=1, completeness=1 if closed else 0.5, timestamp=0,
                provider=1, continuity=1, cross_check=0,
                quality_flags=flags + (() if closed else ("PARTIAL_BAR",)),
            )
            result.append(Bar(
                symbol=symbol, market="cn", asset_type="stock", timeframe=timeframe,
                bar_start=bar_start, bar_end=bar_end, open=open_, high=high, low=low,
                close=close, volume=volume,
                amount=float(row["amount"]) if "amount" in row and pd.notna(row["amount"]) else None,
                provider="stockdata-hub", feed="stockdata_hub_intraday",
                source_timestamp=bar_end, received_at=received_at, session="regular",
                is_closed=closed, is_complete=closed,
                latency_ms=max(0, int((received_at - bar_end.astimezone(timezone.utc)).total_seconds() * 1000)),
                freshness_ms=max(0, int((received_at - bar_end.astimezone(timezone.utc)).total_seconds() * 1000)),
                health=health, quality_flags=health.quality_flags,
            ))
        self._last_health = result[-1].health if result else self._last_health
        return result

    def subscribe(self, symbols: Sequence[str], timeframe: str = "1m", callback: Optional[BarCallback] = None) -> None:
        raise NotImplementedError("historical adapter does not provide subscriptions")

    def get_session_status(self, market: str) -> str:
        return "regular" if market == "cn" else "unsupported"

    def get_provider_health(self) -> MarketDataHealth:
        return self._last_health

    def reconnect(self) -> bool:
        return False


def _as_cn(value: datetime) -> datetime:
    return value.replace(tzinfo=CN_ZONE) if value.tzinfo is None else value.astimezone(CN_ZONE)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _request_days(start: Optional[datetime], end: Optional[datetime]) -> int:
    if start is None or end is None:
        return 30
    return max(1, min(365, (end.date() - start.date()).days + 2))
