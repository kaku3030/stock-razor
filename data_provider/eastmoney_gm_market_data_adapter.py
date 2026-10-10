# -*- coding: utf-8 -*-
"""Read-only Eastmoney/gm adapter for the provider-neutral radar contracts.

The gm client is injected deliberately.  This keeps tests offline, keeps the
token outside the adapter state, and makes the live qualification boundary
explicit: history/current are implemented, streaming is not.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from dataclasses import replace
from typing import Any, Callable, Optional, Protocol, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from .market_data_adapter import (
    Bar,
    BarCallback,
    MarketDataAdapter,
    MarketDataHealth,
    Quote,
    evaluate_health,
)


CN_ZONE = ZoneInfo("Asia/Shanghai")
GM_FIELDS = "symbol,bob,eob,open,high,low,close,volume,amount"
FREQUENCIES = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "60m": "60m", "1d": "1d"}
ETF_PREFIXES = ("15", "16", "18", "50", "51", "56", "58", "159")


class EastmoneyGMClient(Protocol):
    def history(self, **kwargs: Any) -> Any: ...

    def history_n(self, **kwargs: Any) -> Any: ...

    def current(self, **kwargs: Any) -> Any: ...


def normalize_cn_symbol(symbol: str) -> tuple[str, str, str]:
    """Return canonical Stock Razor symbol, gm symbol, and asset type."""

    raw = str(symbol).strip().upper()
    if not raw:
        raise ValueError("symbol is required")
    if "." in raw:
        code, suffix = raw.rsplit(".", 1)
        if suffix in {"SH", "SZ"}:
            market = suffix
        elif suffix in {"SHSE", "SZSE"}:
            market = "SH" if suffix == "SHSE" else "SZ"
        else:
            raise ValueError(f"unsupported CN symbol suffix: {suffix}")
    else:
        code, market = raw, "SH" if raw.startswith(("5", "6", "68", "9")) else "SZ"
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"invalid CN symbol: {symbol}")
    gm_market = "SHSE" if market == "SH" else "SZSE"
    asset_type = "etf" if code.startswith(ETF_PREFIXES) else "stock"
    return f"{code}.{market}", f"{gm_market}.{code}", asset_type


def _timestamp(value: object) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        parsed = parsed.to_pydatetime()
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=CN_ZONE)
    return parsed.astimezone(CN_ZONE)


def _value(row: object, *names: str) -> object:
    for name in names:
        if isinstance(row, dict) and name in row:
            return row[name]
        if hasattr(row, name):
            return getattr(row, name)
    return None


def _rows(payload: Any) -> list[object]:
    if payload is None:
        return []
    if isinstance(payload, pd.DataFrame):
        return [row for _, row in payload.iterrows()]
    if isinstance(payload, dict):
        return [payload]
    return list(payload)


def _number(value: object, *, default: float = 0.0) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    return float(value)


def _present(value: object) -> bool:
    return value is not None and not (isinstance(value, float) and pd.isna(value))


def _timestamp_flags(provider_timestamp: datetime, received_at: datetime) -> list[str]:
    """Expose provider/receiver clock disagreement instead of hiding it."""

    if provider_timestamp > received_at:
        return ["TIMESTAMP_MISMATCH", "PROVIDER_TIMESTAMP_IN_FUTURE"]
    return []


def _quality_flags(
    *,
    row: object,
    eob: Optional[datetime],
    bob: Optional[datetime],
    values: dict[str, float],
    volume: float,
) -> list[str]:
    flags = ["HISTORICAL_QUERY", "NOT_CROSS_CHECKED"]
    if eob is None or bob is None:
        flags.append("MISSING_TIMESTAMP")
    if any(not _present(_value(row, name)) for name in ("open", "high", "low", "close")):
        flags.append("MISSING_OHLCV")
    if not _present(_value(row, "volume", "vol")):
        flags.append("MISSING_OHLCV")
    if not (
        values["low"] <= values["open"] <= values["high"]
        and values["low"] <= values["close"] <= values["high"]
    ):
        flags.append("INVALID_OHLC")
    if volume < 0:
        flags.append("NEGATIVE_VOLUME")
    return list(dict.fromkeys(flags))


def _sequence_flags(bars: list[Bar], timeframe: str) -> list[set[str]]:
    flags = [set(bar.quality_flags) for bar in bars]
    if timeframe == "1d":
        return flags
    step = timedelta(minutes=int(timeframe.removesuffix("m")))
    seen: dict[datetime, int] = {}
    for index, bar in enumerate(bars):
        if bar.bar_start in seen:
            flags[index].add("DUPLICATE_TIMESTAMP")
            flags[seen[bar.bar_start]].add("DUPLICATE_TIMESTAMP")
        else:
            seen[bar.bar_start] = index
        if index == 0:
            continue
        previous = bars[index - 1]
        delta = bar.bar_start - previous.bar_start
        if delta <= timedelta(0):
            flags[index].add("NON_MONOTONIC_TIMESTAMP")
            flags[index - 1].add("NON_MONOTONIC_TIMESTAMP")
        elif (
            delta > step
            and delta <= timedelta(hours=2)
            and not _is_cn_lunch_break(previous, bar)
        ):
            flags[index].add("MISSING_BAR")
            flags[index - 1].add("MISSING_BAR")
    return flags


def _is_cn_lunch_break(previous: Bar, current: Bar) -> bool:
    previous_end = previous.bar_end.astimezone(CN_ZONE).time()
    current_start = current.bar_start.astimezone(CN_ZONE).time()
    return previous_end <= time(11, 30) and current_start >= time(13, 0)


class EastmoneyGMMarketDataAdapter(MarketDataAdapter):
    """Normalize gm historical/current results into Stock Razor V1 facts."""

    supports_direct_timeframes = True

    def __init__(
        self,
        client: EastmoneyGMClient,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        session_resolver: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client
        self._now = now
        self._session_resolver = session_resolver
        self._cache: dict[tuple[object, ...], tuple[Bar, ...]] = {}
        self._last_health = evaluate_health(
            freshness=0,
            completeness=0,
            timestamp=0,
            provider=0,
            continuity=0,
            cross_check=0,
            quality_flags=("NOT_OBSERVED",),
        )

    @classmethod
    def from_environment(
        cls,
        *,
        token_env: str = "EASTMONEY_GM_TOKEN",
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        session_resolver: Optional[Callable[[str], str]] = None,
    ) -> "EastmoneyGMMarketDataAdapter":
        """Construct from a local token without retaining or printing it."""

        import os

        token = os.getenv(token_env, "").strip()
        if not token:
            raise RuntimeError(f"{token_env} is not configured")
        try:
            from gm import api as gm_api
        except ImportError as exc:
            raise RuntimeError("gm package is unavailable") from exc
        gm_api.set_token(token)
        return cls(gm_api, now=now, session_resolver=session_resolver)

    def get_latest_quote(self, symbol: str) -> Quote:
        canonical, gm_symbol, asset_type = normalize_cn_symbol(symbol)
        received_at = self._now()
        rows = _rows(self._client.current(symbols=[gm_symbol]))
        if not rows:
            raise LookupError(f"no Eastmoney/gm current quote available for {canonical}")
        row = rows[0]
        source_timestamp = _timestamp(_value(row, "created_at", "update_time", "last_update", "eob"))
        flags: list[str] = ["NOT_CROSS_CHECKED"]
        if source_timestamp is None:
            source_timestamp = received_at
            flags.append("MISSING_SOURCE_TIMESTAMP")
        else:
            flags.extend(_timestamp_flags(source_timestamp, received_at))
        price = _number(_value(row, "last_price", "price", "close"))
        if price <= 0:
            flags.append("NON_POSITIVE_PRICE")
        health = evaluate_health(
            # A current price without provider time is observable but not
            # currentness-qualified; preserve the existing WATCH_ONLY rule.
            freshness=1,
            completeness=1 if price > 0 else 0,
            timestamp=0.5 if "MISSING_SOURCE_TIMESTAMP" in flags else 1,
            provider=1,
            continuity=1,
            cross_check=0.5,
            quality_flags=flags,
        )
        self._last_health = health
        return Quote(
            symbol=canonical,
            market="cn",
            asset_type=asset_type,
            price=price,
            provider="eastmoney_gm",
            feed="gm_current",
            source_timestamp=source_timestamp.astimezone(timezone.utc),
            received_at=received_at,
            session=self.get_session_status("cn"),
            volume=_value(row, "volume", "vol"),
            amount=_value(row, "amount", "turnover"),
            bid=_value(row, "bid", "bid_price"),
            ask=_value(row, "ask", "ask_price"),
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
        if timeframe not in FREQUENCIES:
            raise NotImplementedError(f"unsupported Eastmoney/gm timeframe: {timeframe}")
        canonical, gm_symbol, asset_type = normalize_cn_symbol(symbol)
        count = min(max(int(limit or 1000), 1), 33000)
        cache_key = (canonical, timeframe, start, end, count)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return list(cached)
        kwargs: dict[str, Any] = {
            "symbol": gm_symbol,
            "frequency": FREQUENCIES[timeframe],
            "fields": GM_FIELDS,
            "df": True,
        }
        if start is None:
            kwargs["count"] = count
            if end is not None:
                kwargs["end_time"] = end.astimezone(CN_ZONE).strftime("%Y-%m-%d %H:%M:%S")
            payload = self._client.history_n(**kwargs)
        else:
            kwargs["start_time"] = start.astimezone(CN_ZONE).isoformat() if start else ""
            kwargs["end_time"] = end.astimezone(CN_ZONE).isoformat() if end else ""
            payload = self._client.history(**kwargs)
        received_at = self._now()
        bars: list[Bar] = []
        minutes = 1440 if timeframe == "1d" else int(timeframe.removesuffix("m"))
        for row in _rows(payload):
            eob = _timestamp(_value(row, "eob", "bar_end"))
            bob = _timestamp(_value(row, "bob", "bar_start"))
            if eob is None:
                continue
            inferred_bob = bob is None
            if inferred_bob:
                bob = eob - timedelta(minutes=minutes)
            values = {name: _number(_value(row, name)) for name in ("open", "high", "low", "close")}
            volume = _number(_value(row, "volume", "vol"))
            amount = _value(row, "amount", "turnover")
            flags = _quality_flags(
                row=row,
                eob=eob,
                bob=None if inferred_bob else bob,
                values=values,
                volume=volume,
            )
            eob_utc = eob.astimezone(timezone.utc)
            received_utc = received_at.astimezone(timezone.utc)
            flags.extend(_timestamp_flags(eob_utc, received_utc))
            is_closed = eob_utc <= received_utc
            if not is_closed:
                flags.append("PARTIAL_BAR")
            health = evaluate_health(
                freshness=1,
                completeness=1,
                timestamp=1,
                provider=1,
                continuity=0.5,
                cross_check=0.5,
                quality_flags=flags,
            )
            latency_ms = int((received_utc - eob_utc).total_seconds() * 1000)
            bars.append(Bar(
                symbol=canonical,
                market="cn",
                asset_type=asset_type,
                timeframe=timeframe,
                bar_start=bob.astimezone(timezone.utc),
                bar_end=eob_utc,
                open=values["open"], high=values["high"], low=values["low"], close=values["close"],
                volume=volume,
                amount=_number(amount) if amount is not None else None,
                provider="eastmoney_gm",
                feed="gm_history",
                source_timestamp=eob_utc,
                received_at=received_utc,
                session="closed",
                is_closed=is_closed,
                is_complete=is_closed and not inferred_bob,
                latency_ms=latency_ms,
                freshness_ms=latency_ms,
                health=health,
                quality_flags=health.quality_flags,
            ))
        bars.sort(key=lambda item: item.bar_start)
        if not bars:
            raise LookupError(f"no Eastmoney/gm historical bars available for {canonical} {timeframe}")
        sequence_flags = _sequence_flags(bars, timeframe)
        validated: list[Bar] = []
        for bar, flags in zip(bars, sequence_flags):
            merged_flags = tuple(dict.fromkeys((*bar.quality_flags, *sorted(flags))))
            health = evaluate_health(
                freshness=1,
                completeness=0 if {"MISSING_OHLCV", "MISSING_TIMESTAMP"}.intersection(merged_flags) else 1,
                timestamp=0 if {"MISSING_TIMESTAMP", "DUPLICATE_TIMESTAMP", "NON_MONOTONIC_TIMESTAMP"}.intersection(merged_flags) else 1,
                provider=1,
                continuity=0 if {"MISSING_BAR", "DUPLICATE_TIMESTAMP", "NON_MONOTONIC_TIMESTAMP"}.intersection(merged_flags) else 1,
                cross_check=0.5,
                quality_flags=merged_flags,
            )
            validated.append(replace(bar, health=health, quality_flags=health.quality_flags))
        bars = validated
        self._cache[cache_key] = tuple(bars)
        self._last_health = bars[-1].health or self._last_health
        return list(bars)

    def subscribe(self, symbols: Sequence[str], timeframe: str = "1m", callback: Optional[BarCallback] = None) -> None:
        raise NotImplementedError("Eastmoney/gm live subscribe is UNKNOWN/BLOCKED pending session qualification")

    def get_session_status(self, market: str) -> str:
        if market != "cn":
            return "unsupported"
        return str(self._session_resolver(market)) if self._session_resolver else "unknown"

    def get_provider_health(self) -> MarketDataHealth:
        return self._last_health

    def reconnect(self) -> bool:
        return False
