# -*- coding: utf-8 -*-
"""Read-only Alpaca US market-data adapter for MarketDataAdapter V1."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, time, timedelta, timezone
from typing import Callable, Optional, Sequence
from zoneinfo import ZoneInfo

from .market_data_adapter import (
    Bar,
    BarCallback,
    MarketDataAdapter,
    MarketDataHealth,
    Quote,
    evaluate_health,
)


NY_ZONE = ZoneInfo("America/New_York")
ALPACA_DATA_URL = "https://data.alpaca.markets"


def _value(raw: object, *names: str) -> object:
    for name in names:
        if isinstance(raw, dict) and name in raw:
            return raw[name]
        if hasattr(raw, name):
            return getattr(raw, name)
    return None


def _timestamp(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


def _session_at(timestamp: datetime) -> str:
    local_time = timestamp.astimezone(NY_ZONE).time()
    if time(4) <= local_time < time(9, 30):
        return "premarket"
    if time(9, 30) <= local_time < time(16):
        return "regular"
    if time(16) <= local_time < time(20):
        return "afterhours"
    return "overnight"


class AlpacaRestMarketDataClient:
    """Small authenticated client for Alpaca's read-only stock data endpoints."""

    def __init__(self, api_key: str, api_secret: str, *, base_url: str = ALPACA_DATA_URL) -> None:
        if not api_key or not api_secret:
            raise ValueError("Alpaca market-data credentials are required")
        self._headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
        self._base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict[str, object]) -> dict:
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value not in (None, "")})
        request = urllib.request.Request(f"{self._base_url}{path}?{query}", headers=self._headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_bars(self, symbol: str, *, start: str, end: str, limit: int, feed: str) -> list[dict]:
        payload = self._get(
            f"/v2/stocks/{urllib.parse.quote(symbol)}/bars",
            {"timeframe": "1Min", "start": start, "end": end, "limit": limit, "feed": feed, "sort": "desc"},
        )
        return list(payload.get("bars") or [])

    def get_latest_bar(self, symbol: str, *, feed: str) -> dict:
        payload = self._get(f"/v2/stocks/{urllib.parse.quote(symbol)}/bars/latest", {"feed": feed})
        return dict(payload.get("bar") or {})

    def get_latest_quote(self, symbol: str, *, feed: str) -> dict:
        payload = self._get(f"/v2/stocks/{urllib.parse.quote(symbol)}/quotes/latest", {"feed": feed})
        return dict(payload.get("quote") or {})


class AlpacaMarketDataAdapter(MarketDataAdapter):
    def __init__(
        self,
        rest_client: object,
        *,
        stream_client: object | None = None,
        feed: str = "iex",
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        normalized_feed = str(feed).strip().lower()
        if normalized_feed not in {"iex", "sip", "delayed_sip", "boats", "overnight", "otc"}:
            raise ValueError(f"unsupported Alpaca feed: {feed}")
        self._rest = rest_client
        self._stream = stream_client
        self._feed = normalized_feed
        self._now = now
        self._last_health = evaluate_health(
            freshness=0,
            completeness=0,
            timestamp=0,
            provider=0,
            continuity=0,
            cross_check=0,
            quality_flags=("NOT_OBSERVED",),
        )

    def _normalize_bar(self, symbol: str, raw: object, *, updated: bool = False) -> Bar:
        received_at = self._now()
        timestamp = _timestamp(_value(raw, "t", "timestamp"))
        flags = ["NOT_CROSS_CHECKED"]
        if timestamp is None:
            flags.append("TIMESTAMP_MISMATCH")
            timestamp = received_at
        if updated:
            flags.append("UPDATED_BAR")
        bar_end = timestamp + timedelta(minutes=1)
        numeric = {
            "open": float(_value(raw, "o", "open") or 0),
            "high": float(_value(raw, "h", "high") or 0),
            "low": float(_value(raw, "l", "low") or 0),
            "close": float(_value(raw, "c", "close") or 0),
            "volume": float(_value(raw, "v", "volume") or 0),
        }
        if not (
            numeric["low"] <= numeric["open"] <= numeric["high"]
            and numeric["low"] <= numeric["close"] <= numeric["high"]
        ):
            flags.append("INVALID_OHLC")
        if numeric["volume"] < 0:
            flags.append("NEGATIVE_VOLUME")
        closed = received_at >= bar_end
        if not closed:
            flags.append("PARTIAL_BAR")
        health = evaluate_health(
            freshness=1,
            completeness=1,
            timestamp=1 if "TIMESTAMP_MISMATCH" not in flags else 0,
            provider=1,
            continuity=1,
            cross_check=0.5,
            quality_flags=flags,
        )
        amount = _value(raw, "amount")
        return Bar(
            symbol=symbol.upper(),
            market="us",
            asset_type="stock",
            timeframe="1m",
            bar_start=timestamp,
            bar_end=bar_end,
            open=numeric["open"],
            high=numeric["high"],
            low=numeric["low"],
            close=numeric["close"],
            volume=numeric["volume"],
            amount=float(amount) if amount is not None else None,
            vwap=float(_value(raw, "vw", "vwap")) if _value(raw, "vw", "vwap") is not None else None,
            provider="alpaca",
            feed=self._feed,
            session=_session_at(timestamp),
            source_timestamp=bar_end,
            received_at=received_at,
            is_closed=closed,
            is_complete=closed,
            latency_ms=max(0, int((received_at - bar_end).total_seconds() * 1000)),
            freshness_ms=max(0, int((received_at - bar_end).total_seconds() * 1000)),
            health=health,
            quality_flags=health.quality_flags,
        )

    def get_latest_quote(self, symbol: str) -> Quote:
        code = symbol.strip().upper()
        bar = self._rest.get_latest_bar(code, feed=self._feed)
        raw_quote = self._rest.get_latest_quote(code, feed=self._feed)
        if not bar:
            raise LookupError(f"no Alpaca latest bar available for {code}")
        received_at = self._now()
        bar_timestamp = _timestamp(_value(bar, "t", "timestamp"))
        quote_timestamp = _timestamp(_value(raw_quote, "t", "timestamp"))
        timestamps = [value for value in (bar_timestamp, quote_timestamp) if value is not None]
        source_timestamp = max(timestamps) if timestamps else received_at
        price = float(_value(bar, "c", "close") or 0)
        flags = [] if timestamps else ["MISSING_SOURCE_TIMESTAMP"]
        if price <= 0:
            flags.append("NON_POSITIVE_PRICE")
        health = evaluate_health(
            freshness=1,
            completeness=1 if price > 0 else 0,
            timestamp=1 if timestamps else 0.5,
            provider=1,
            continuity=1,
            cross_check=0.5,
            quality_flags=flags,
        )
        self._last_health = health
        return Quote(
            symbol=code,
            market="us",
            asset_type="stock",
            price=price,
            provider="alpaca",
            feed=self._feed,
            source_timestamp=source_timestamp,
            received_at=received_at,
            session=_session_at(source_timestamp),
            bid=_value(raw_quote, "bp", "bid_price"),
            ask=_value(raw_quote, "ap", "ask_price"),
            volume=_value(bar, "v", "volume"),
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
        if timeframe != "1m":
            raise NotImplementedError("Alpaca V1 exposes raw 1m bars only")
        rows = self._rest.get_bars(
            symbol.strip().upper(),
            start=start.astimezone(timezone.utc).isoformat() if start else "",
            end=end.astimezone(timezone.utc).isoformat() if end else "",
            limit=min(max(int(limit or 1000), 1), 10000),
            feed=self._feed,
        )
        bars = [self._normalize_bar(symbol, raw) for raw in rows]
        bars.sort(key=lambda item: item.bar_start)
        if bars:
            self._last_health = bars[-1].health or self._last_health
        return bars

    def subscribe(
        self,
        symbols: Sequence[str],
        timeframe: str = "1m",
        callback: Optional[BarCallback] = None,
    ) -> None:
        if timeframe != "1m":
            raise NotImplementedError("Alpaca V1 subscribes to raw 1m bars only")
        if self._stream is None:
            raise RuntimeError("Alpaca stream client is not configured")
        if callback is None:
            raise ValueError("callback is required for Alpaca subscriptions")
        codes = tuple(symbol.strip().upper() for symbol in symbols)

        async def on_bar(raw: object) -> None:
            callback(self._normalize_bar(str(_value(raw, "S", "symbol")), raw))

        async def on_updated_bar(raw: object) -> None:
            callback(self._normalize_bar(str(_value(raw, "S", "symbol")), raw, updated=True))

        self._stream.subscribe_bars(on_bar, *codes)
        self._stream.subscribe_updated_bars(on_updated_bar, *codes)

    def get_session_status(self, market: str) -> str:
        return _session_at(self._now()) if market == "us" else "unsupported"

    def get_provider_health(self) -> MarketDataHealth:
        return self._last_health

    def reconnect(self) -> bool:
        return False
