# -*- coding: utf-8 -*-
"""Read-only Alpaca US market-data adapter for MarketDataAdapter V1."""

from __future__ import annotations

import json
import time
import threading
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
# Snapshot prices sourced from one-minute bars are not tick quotes. An older
# last bar must never receive a healthy/currentness claim from a newer BBO.
MAX_LATEST_BAR_AGE = timedelta(minutes=3)
MAX_BBO_BAR_TIME_SKEW = timedelta(minutes=1)


def _value(raw: object, *names: str) -> object:
    for name in names:
        if isinstance(raw, dict) and name in raw:
            return raw[name]
        if hasattr(raw, name):
            return getattr(raw, name)
    return None


def _timestamp(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo is not None else None
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
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
        self._stream_thread: threading.Thread | None = None
        self._stream_lock = threading.RLock()
        self._subscribed = False
        self._closed = False
        self._generation = 0
        self._stream_error: BaseException | None = None
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

    def _normalize_bar(self, symbol: str, raw: object, *, updated: bool = False, live: bool = False) -> Bar:
        received_at = self._now()
        timestamp = _timestamp(_value(raw, "t", "timestamp"))
        flags = ["NOT_CROSS_CHECKED"]
        if timestamp is None:
            flags.append("TIMESTAMP_MISMATCH")
            timestamp = received_at
        if updated:
            flags.append("UPDATED_BAR")
        if not live:
            flags.append("HISTORICAL_QUERY")
        if self._feed == "delayed_sip":
            flags.append("DELAYED_FEED")
        bar_end = timestamp + timedelta(minutes=1)
        age = received_at - bar_end
        if age < -timedelta(minutes=1):
            flags.append("TIMESTAMP_MISMATCH")
        if live and age > MAX_LATEST_BAR_AGE:
            flags.append("STALE")
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
            freshness=0 if (not live or "STALE" in flags or "DELAYED_FEED" in flags) else 1,
            completeness=1 if closed else 0.5,
            timestamp=0 if "TIMESTAMP_MISMATCH" in flags else 1,
            provider=1,
            continuity=0 if live else 1,  # one bar cannot prove a stream's continuity
            cross_check=0.5,
            quality_flags=flags,
        )
        amount = _value(raw, "amount")
        latency_ms = max(0, int(age.total_seconds() * 1000))
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
            is_complete=closed and "TIMESTAMP_MISMATCH" not in flags,
            latency_ms=latency_ms,
            freshness_ms=latency_ms,
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
        # Quote.price comes from bar.c: its source time MUST be that bar's end,
        # never max(bar_timestamp, quote_timestamp). Bid/ask have separate source
        # semantics and are suppressed when their timestamp cannot be trusted.
        flags: list[str] = []
        if bar_timestamp is None:
            flags.append("MISSING_SOURCE_TIMESTAMP")
        source_timestamp = bar_timestamp + timedelta(minutes=1) if bar_timestamp else received_at
        age = received_at - source_timestamp
        if age < -timedelta(minutes=1):
            flags.append("TIMESTAMP_MISMATCH")
        if age > MAX_LATEST_BAR_AGE:
            flags.append("STALE")
        if self._feed == "delayed_sip":
            flags.append("DELAYED_FEED")
        price = float(_value(bar, "c", "close") or 0)
        if price <= 0:
            flags.append("NON_POSITIVE_PRICE")
        bid = ask = None
        if quote_timestamp is None:
            flags.append("MISSING_QUOTE_TIMESTAMP")
        elif bar_timestamp is None or abs(quote_timestamp - source_timestamp) > MAX_BBO_BAR_TIME_SKEW:
            flags.append("BBO_TIME_NOT_COMPARABLE")
        else:
            bid = _value(raw_quote, "bp", "bid_price")
            ask = _value(raw_quote, "ap", "ask_price")
            if quote_timestamp != source_timestamp:
                flags.append("BBO_TIME_DIFFERS_FROM_PRICE")
        health = evaluate_health(
            freshness=0 if "STALE" in flags or "DELAYED_FEED" in flags else 1,
            completeness=1 if price > 0 else 0,
            timestamp=0 if bar_timestamp is None or "TIMESTAMP_MISMATCH" in flags else 1,
            provider=1,
            continuity=0,  # latest snapshot is not proof of continuous minute coverage
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
            bid=bid,
            ask=ask,
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
        codes = tuple(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
        if not codes:
            raise ValueError("at least one Alpaca symbol is required")
        with self._stream_lock:
            if self._closed:
                raise RuntimeError("Alpaca adapter is closed")
            if self._subscribed:
                raise RuntimeError("Alpaca adapter already subscribed")
            self._subscribed = True
            generation = self._generation

        async def on_bar(raw: object) -> None:
            if not self._closed and self._generation == generation:
                callback(self._normalize_bar(str(_value(raw, "S", "symbol")), raw, live=True))

        async def on_updated_bar(raw: object) -> None:
            if not self._closed and self._generation == generation:
                callback(self._normalize_bar(str(_value(raw, "S", "symbol")), raw, updated=True, live=True))

        try:
            self._stream.subscribe_bars(on_bar, *codes)
            self._stream.subscribe_updated_bars(on_updated_bar, *codes)
            # alpaca-py 0.44.0 run() owns asyncio.run(); never call it on
            # the API event loop. A running thread is NOT proof of auth/readiness.
            run = getattr(self._stream, "run", None)
            if not callable(run):
                raise RuntimeError("Alpaca stream has no run() lifecycle")
            def worker() -> None:
                try:
                    run()
                except BaseException as exc:
                    self._stream_error = exc
            thread = threading.Thread(target=worker, name="alpaca-market-stream", daemon=True)
            self._stream_thread = thread
            thread.start()
            if not thread.is_alive():
                raise RuntimeError("Alpaca stream terminated during startup")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        with self._stream_lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            stream = self._stream
            thread = self._stream_thread
        if stream is not None and thread is not None:
            stop = getattr(stream, "stop", None)
            if not callable(stop):
                raise RuntimeError("Alpaca stream has no stop() lifecycle")
            # alpaca-py 0.44.0 initializes _loop inside run(); stop() raises
            # AttributeError if called before that loop exists.
            if hasattr(stream, "_loop"):
                deadline = time.monotonic() + 2
                while getattr(stream, "_loop", None) is None and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.01)
                if getattr(stream, "_loop", None) is None and thread.is_alive():
                    raise RuntimeError("Alpaca stream loop did not initialize for safe shutdown")
            if thread.is_alive():
                stop()
            if thread is not threading.current_thread():
                thread.join(timeout=8)
                if thread.is_alive():
                    raise RuntimeError("Alpaca stream did not terminate after stop()")

    def get_session_status(self, market: str) -> str:
        return _session_at(self._now()) if market == "us" else "unsupported"

    def get_provider_health(self) -> MarketDataHealth:
        return self._last_health

    def reconnect(self) -> bool:
        return False
