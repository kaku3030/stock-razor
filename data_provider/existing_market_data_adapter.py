# -*- coding: utf-8 -*-
"""Read-only bridge from the existing fetcher manager to MarketDataAdapter V1."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

import pandas as pd

from .market_data_adapter import (
    Bar,
    BarCallback,
    MarketDataAdapter,
    MarketDataHealth,
    Quote,
    evaluate_health,
)


def _utc_datetime(value: object, *, fallback: Optional[datetime] = None) -> Optional[datetime]:
    if value in (None, ""):
        return fallback
    try:
        parsed = pd.to_datetime(value, utc=True)
    except (TypeError, ValueError):
        return fallback
    return parsed.to_pydatetime()


def _market_for(symbol: str, declared: Optional[str] = None) -> str:
    if declared:
        return str(declared).strip().lower()
    code = (symbol or "").strip().upper()
    if code.startswith("HK") or code.endswith(".HK"):
        return "hk"
    suffix = code.rsplit(".", 1)[1] if "." in code else ""
    suffix_markets = {"T": "jp", "KS": "kr", "KQ": "kr", "TW": "tw", "TWO": "tw"}
    if suffix in suffix_markets:
        return suffix_markets[suffix]
    return "us" if code.isalpha() else "cn"


class ExistingMarketDataAdapter(MarketDataAdapter):
    """Normalize existing manager output without adding a new provider dependency.

    V1 deliberately supports snapshots and daily bars only. Intraday streaming
    belongs to provider-specific adapters and must not be simulated by polling.
    """

    def __init__(
        self,
        manager: object,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        session_resolver: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._manager = manager
        self._now = now
        self._session_resolver = session_resolver
        self._last_health = evaluate_health(
            freshness=0,
            completeness=0,
            timestamp=0,
            provider=0,
            continuity=0,
            cross_check=0,
            quality_flags=("NOT_OBSERVED",),
        )

    def get_latest_quote(self, symbol: str) -> Quote:
        raw = self._manager.get_realtime_quote(symbol, log_final_failure=False)
        if raw is None:
            self._last_health = evaluate_health(
                freshness=0,
                completeness=0,
                timestamp=0,
                provider=0,
                continuity=0,
                cross_check=0,
                quality_flags=("PROVIDER_UNAVAILABLE",),
            )
            raise LookupError(f"no realtime quote available for {symbol}")

        received_at = _utc_datetime(getattr(raw, "fetched_at", None), fallback=self._now())
        source_timestamp = _utc_datetime(getattr(raw, "provider_timestamp", None))
        missing_fields = tuple(str(item).upper() for item in (getattr(raw, "missing_fields", None) or ()))
        flags = list(missing_fields)
        if source_timestamp is None:
            flags.append("MISSING_SOURCE_TIMESTAMP")
            source_timestamp = received_at
        if getattr(raw, "is_stale", False):
            flags.append("STALE")
        if getattr(raw, "fallback_from", None):
            flags.append("FALLBACK_PROVIDER")

        price = getattr(raw, "price", None)
        if price is None or float(price) <= 0:
            flags.append("NON_POSITIVE_PRICE")
        health = evaluate_health(
            freshness=0 if getattr(raw, "is_stale", False) else 1,
            completeness=1 if price is not None and not missing_fields else 0.5,
            timestamp=1 if getattr(raw, "provider_timestamp", None) else 0.5,
            provider=1,
            continuity=1,
            cross_check=0.5,
            quality_flags=flags,
        )
        self._last_health = health

        source = getattr(raw, "source", "existing")
        provider = getattr(source, "value", source)
        market = _market_for(symbol, getattr(raw, "market", None))
        return Quote(
            symbol=symbol,
            market=market,
            asset_type="stock",
            price=float(price or 0),
            provider=str(provider),
            source_timestamp=source_timestamp,
            received_at=received_at,
            session=self.get_session_status(market),
            volume=getattr(raw, "volume", None),
            amount=getattr(raw, "amount", None),
            health=health,
            quality_flags=health.quality_flags,
        )

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> list[Bar]:
        if timeframe not in {"1d", "daily"}:
            raise NotImplementedError("existing provider bridge supports daily bars only")
        start_date = start.date().isoformat() if start else None
        end_date = end.date().isoformat() if end else None
        frame, provider = self._manager.get_daily_data(
            symbol,
            start_date=start_date,
            end_date=end_date,
            days=max(limit or 30, 1),
        )
        if frame is None or frame.empty:
            return []

        rows: list[Bar] = []
        selected = frame.tail(limit) if limit else frame
        received_at = self._now()
        market = _market_for(symbol)
        for _, row in selected.iterrows():
            timestamp = _utc_datetime(row.get("date"))
            if timestamp is None:
                continue
            values = {name: row.get(name) for name in ("open", "high", "low", "close", "volume")}
            flags: list[str] = ["NOT_CROSS_CHECKED"]
            complete = all(pd.notna(value) for value in values.values())
            if not complete:
                flags.append("PARTIAL_BAR")
            numeric = {name: float(value) for name, value in values.items() if pd.notna(value)}
            if complete and not (
                numeric["low"] <= numeric["open"] <= numeric["high"]
                and numeric["low"] <= numeric["close"] <= numeric["high"]
            ):
                flags.append("INVALID_OHLC")
            if numeric.get("volume", 0) < 0:
                flags.append("NEGATIVE_VOLUME")
            health = evaluate_health(
                freshness=1,
                completeness=1 if complete else 0.5,
                timestamp=1,
                provider=1,
                continuity=1,
                cross_check=0.5,
                quality_flags=flags,
            )
            rows.append(
                Bar(
                    symbol=symbol,
                    market=market,
                    asset_type="stock",
                    timeframe="1d",
                    bar_start=timestamp,
                    bar_end=timestamp,
                    open=numeric.get("open", 0),
                    high=numeric.get("high", 0),
                    low=numeric.get("low", 0),
                    close=numeric.get("close", 0),
                    volume=numeric.get("volume", 0),
                    amount=float(row["amount"]) if "amount" in row and pd.notna(row["amount"]) else None,
                    provider=str(provider),
                    source_timestamp=timestamp,
                    received_at=received_at,
                    session="closed",
                    is_closed=True,
                    is_complete=complete,
                    health=health,
                    quality_flags=health.quality_flags,
                )
            )
        if rows:
            self._last_health = rows[-1].health or self._last_health
        return rows

    def subscribe(
        self,
        symbols: Sequence[str],
        timeframe: str = "1m",
        callback: Optional[BarCallback] = None,
    ) -> None:
        raise NotImplementedError("existing provider bridge does not emulate streaming")

    def get_session_status(self, market: str) -> str:
        if self._session_resolver is None:
            return "unknown"
        return str(self._session_resolver(market))

    def get_provider_health(self) -> MarketDataHealth:
        return self._last_health

    def reconnect(self) -> bool:
        return False
